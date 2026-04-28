"""DNS-01 challenge 处理器。"""

from __future__ import annotations

import logging

from certkeeper.challenges.base import ChallengeHandler
from certkeeper.config import CertificateConfig, NamedResourceConfig
from certkeeper.dns.base import DnsProvider, ProviderRegistry

logger = logging.getLogger(__name__)


class Dns01ChallengeHandler(ChallengeHandler):
    """为校验创建并删除 DNS TXT 记录。"""

    def __init__(
        self,
        *,
        dns_provider_configs: dict[str, NamedResourceConfig],
        provider_registry: ProviderRegistry[DnsProvider],
    ) -> None:
        self.dns_provider_configs = dns_provider_configs
        self.provider_registry = provider_registry

    def prepare(self, certificate: CertificateConfig, validation: str = "") -> None:
        provider = self._resolve_provider(certificate)
        domain = certificate.domain.lstrip("*.")
        record_name = f"_acme-challenge.{domain}"
        logger.info("创建 DNS TXT 记录: %s (域名: %s, 使用 DNS 提供商: %s)", record_name, domain, certificate.dns_provider)
        provider.create_txt_record(
            domain,
            record_name,
            validation,
        )
        logger.info("DNS TXT 记录已创建: %s", record_name)

    def cleanup(self, certificate: CertificateConfig, validation: str = "") -> None:
        provider = self._resolve_provider(certificate)
        domain = certificate.domain.lstrip("*.")
        record_name = f"_acme-challenge.{domain}"
        logger.info("删除 DNS TXT 记录: %s", record_name)
        provider.delete_txt_record(
            domain,
            record_name,
            validation,
        )
        logger.info("DNS TXT 记录已删除: %s", record_name)

    def _resolve_provider(self, certificate: CertificateConfig) -> DnsProvider:
        if not certificate.dns_provider:
            raise ValueError("dns_provider is required for dns-01 challenges.")
        provider_config = self.dns_provider_configs[certificate.dns_provider]
        return self.provider_registry.create(provider_config)
