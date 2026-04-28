"""证书编排管理器。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from certkeeper.config import AppConfig, CertificateConfig
from certkeeper.core.store import CertificateStatus, Store
from certkeeper.deployers.base import Deployer, ProviderRegistry
from certkeeper.notifications.base import ExpiryReminder, Notifier, ReminderSummary

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CertificateMaterial:
    fullchain_pem: str
    private_key_pem: str


@dataclass(slots=True)
class CertificateCheck:
    domain: str
    needs_renewal: bool
    reason: str
    status: CertificateStatus


@dataclass(slots=True)
class CertificateApplyResult:
    domain: str
    renewed: bool
    deployed_targets: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ApplySummary:
    results: list[CertificateApplyResult]

    @property
    def exit_code(self) -> int:
        if not self.results:
            return 0
        failures = sum(1 for item in self.results if item.errors)
        if failures == 0:
            return 0
        if failures == len(self.results):
            return 2
        return 1


class Manager:
    """协调证书检查、续期、部署与通知流程。"""

    def __init__(
        self,
        *,
        config: AppConfig,
        store: Store,
        acme_client,
        challenge_handlers: dict[str, object],
        deployer_registry: ProviderRegistry[Deployer],
        notifier_registry: ProviderRegistry[Notifier],
    ) -> None:
        self.config = config
        self.store = store
        self.acme_client = acme_client
        self.challenge_handlers = challenge_handlers
        self.deployer_registry = deployer_registry
        self.notifier_registry = notifier_registry

    def check_certificates(self) -> list[CertificateCheck]:
        days_before_expiry = self.config.scheduler.renewal_days
        logger.info("开始检查证书，续期阈值: %d 天", days_before_expiry)
        checks: list[CertificateCheck] = []
        for certificate in self.config.certificates:
            logger.debug("检查证书: %s", certificate.domain)
            status = self.store.get_certificate_status(certificate.domain)
            check = self._build_check(certificate, status, days_before_expiry)
            logger.info(
                "证书 %s: needs_renewal=%s, reason=%s, days_left=%s",
                certificate.domain,
                check.needs_renewal,
                check.reason,
                status.days_until_expiry if status.days_until_expiry is not None else "N/A",
            )
            checks.append(check)
        return checks

    def send_expiry_reminders(self) -> None:
        """检查所有证书到期情况，发送到期提醒邮件。"""

        reminder_days = self.config.scheduler.reminder_days
        reminders: list[ExpiryReminder] = []
        logger.info("开始检查证书到期情况，提醒阈值: %d 天", reminder_days)

        for certificate in self.config.certificates:
            status = self.store.get_certificate_status(certificate.domain)
            if not status.exists or status.days_until_expiry is None:
                logger.debug("证书 %s: 跳过 (exists=%s, days_until_expiry=%s)", certificate.domain, status.exists, status.days_until_expiry)
                continue
            if status.days_until_expiry <= reminder_days:
                logger.info("证书 %s 即将到期: 剩余 %d 天", certificate.domain, status.days_until_expiry)
                reminders.append(ExpiryReminder(
                    domain=certificate.domain,
                    days_until_expiry=status.days_until_expiry,
                    expires_at=status.expires_at.strftime("%Y-%m-%d %H:%M UTC") if status.expires_at else None,
                ))

        if not reminders:
            return

        reminder_summary = ReminderSummary(reminders=reminders, renewal_days=self.config.scheduler.renewal_days)
        for resource in self.config.notifications.values():
            try:
                notifier = self.notifier_registry.create(resource)
                notifier.notify_reminder(reminder_summary)
            except Exception:
                logger.exception("发送到期提醒通知失败: %s", resource.name)

    def apply(self, *, force: bool = False, domain: str | None = None) -> ApplySummary:
        selected = [item for item in self.config.certificates if domain is None or item.domain == domain]
        logger.info("开始 apply 流程: force=%s, domain=%s, 共 %d 个证书", force, domain, len(selected))
        results: list[CertificateApplyResult] = []

        for certificate in selected:
            logger.info("处理证书: %s", certificate.domain)
            status = self.store.get_certificate_status(certificate.domain)
            check = self._build_check(certificate, status, self.config.scheduler.renewal_days)
            renewed = force or check.needs_renewal
            result = CertificateApplyResult(domain=certificate.domain, renewed=renewed)

            try:
                if renewed:
                    logger.info("开始续期证书: %s (原因: %s)", certificate.domain, check.reason)
                    material = self._renew_certificate(certificate)
                    logger.info("证书续期成功: %s", certificate.domain)
                    written = self.store.save_certificate(
                        certificate.domain,
                        material.fullchain_pem,
                        material.private_key_pem,
                    )
                    logger.info("证书已保存: fullchain=%s, key=%s", written.fullchain_path, written.private_key_path)
                    deployed_targets = self._deploy_certificate(certificate, written.fullchain_path, written.private_key_path)
                    result.deployed_targets = deployed_targets
                    self.store.record_result(
                        domain=certificate.domain,
                        expires_at=self.store.get_certificate_status(certificate.domain).expires_at,
                        renewed_at=datetime.now(UTC),
                        deploy_results={target: "success" for target in deployed_targets},
                    )
                else:
                    logger.info("证书 %s 无需续期 (状态: %s)", certificate.domain, check.reason)
            except Exception as exc:  # noqa: BLE001
                logger.error("证书 %s 处理失败: %s", certificate.domain, exc, exc_info=True)
                result.errors.append(str(exc))

            results.append(result)

        summary = ApplySummary(results=results)
        self._notify(summary)
        return summary

    def deploy(self, domain: str | None = None) -> ApplySummary:
        """将本地已存在的证书重新部署到配置目标。"""

        selected = [item for item in self.config.certificates if domain is None or item.domain == domain]
        logger.info("开始 deploy 流程: domain=%s, 共 %d 个证书", domain, len(selected))
        results: list[CertificateApplyResult] = []

        for certificate in selected:
            logger.info("重新部署证书: %s", certificate.domain)
            status = self.store.get_certificate_status(certificate.domain)
            result = CertificateApplyResult(domain=certificate.domain, renewed=False)

            try:
                if not status.exists:
                    raise FileNotFoundError(f"No local certificate available for {certificate.domain}.")

                deployed_targets = self._deploy_certificate(
                    certificate,
                    status.fullchain_path,
                    status.private_key_path,
                )
                result.deployed_targets = deployed_targets
                self.store.record_result(
                    domain=certificate.domain,
                    expires_at=status.expires_at,
                    deploy_results={target: "success" for target in deployed_targets},
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("证书 %s 部署失败: %s", certificate.domain, exc, exc_info=True)
                result.errors.append(str(exc))

            results.append(result)

        summary = ApplySummary(results=results)
        self._notify(summary)
        return summary

    def _build_check(
        self,
        certificate: CertificateConfig,
        status: CertificateStatus,
        days_before_expiry: int,
    ) -> CertificateCheck:
        if not status.exists:
            return CertificateCheck(domain=certificate.domain, needs_renewal=True, reason="missing", status=status)
        if status.days_until_expiry is None:
            return CertificateCheck(domain=certificate.domain, needs_renewal=True, reason="unknown-expiry", status=status)
        if status.days_until_expiry < days_before_expiry:
            return CertificateCheck(domain=certificate.domain, needs_renewal=True, reason="expiring", status=status)
        return CertificateCheck(domain=certificate.domain, needs_renewal=False, reason="healthy", status=status)

    def _renew_certificate(self, certificate: CertificateConfig) -> CertificateMaterial:
        handler = self.challenge_handlers[certificate.challenge]
        return self.acme_client.obtain_certificate(certificate, handler)

    def _deploy_certificate(self, certificate: CertificateConfig, cert_path, key_path) -> list[str]:
        deployed_targets: list[str] = []
        logger.info("开始部署证书 %s 到 %d 个目标: %s", certificate.domain, len(certificate.deploy_to), certificate.deploy_to)
        for target_name in certificate.deploy_to:
            target_config = self.config.deployers[target_name]
            logger.info("部署到目标 [%s] (类型: %s)", target_name, target_config.type)
            deployer = self.deployer_registry.create(target_config)
            try:
                deployer.deploy(certificate.domain, cert_path, key_path)
                logger.info("部署成功: %s -> %s", certificate.domain, target_name)
            except Exception as exc:
                logger.error("部署失败: %s -> %s: %s", certificate.domain, target_name, exc)
                raise RuntimeError(
                    f"部署目标 [{target_name}] ({target_config.type}) 失败: {exc}"
                ) from exc
            deployed_targets.append(target_name)
        return deployed_targets

    def _notify(self, summary: ApplySummary) -> None:
        # 有续期、部署或错误时才发送处理结果通知
        if not summary.results:
            return
        renewed = any(r.renewed for r in summary.results)
        has_errors = any(r.errors for r in summary.results)
        has_deployments = any(r.deployed_targets for r in summary.results)
        if not renewed and not has_errors and not has_deployments:
            return

        for resource in self.config.notifications.values():
            try:
                notifier = self.notifier_registry.create(resource)
                notifier.notify(summary)
            except Exception:
                logger.exception("发送通知失败: %s", resource.name)
