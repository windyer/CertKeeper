"""配置加载相关辅助函数。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from certkeeper.exceptions import ConfigurationError

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


@dataclass(slots=True)
class AcmeConfig:
    directory: str
    email: str
    account_key: str


@dataclass(slots=True)
class SchedulerConfig:
    enabled: bool = True
    interval: str = "daily"
    time: str = "03:00"
    reminder_days: int = 30
    renewal_days: int = 30


@dataclass(slots=True)
class NamedResourceConfig:
    name: str
    type: str
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CertificateConfig:
    domain: str
    san: list[str]
    challenge: str
    dns_provider: str | None
    http_root: str | None
    deploy_to: list[str]


@dataclass(slots=True)
class WebUiConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    base_url: str = "http://127.0.0.1:8080"
    session_secret: str | None = None
    admin_username: str | None = None
    admin_password_hash: str | None = None


@dataclass(slots=True)
class AppConfig:
    path: Path
    acme: AcmeConfig
    scheduler: SchedulerConfig
    notifications: dict[str, NamedResourceConfig]
    dns_providers: dict[str, NamedResourceConfig]
    deployers: dict[str, NamedResourceConfig]
    certificates: list[CertificateConfig]
    web_ui: WebUiConfig = field(default_factory=WebUiConfig)


def load_raw_config(path: str | Path) -> dict[str, Any]:
    """将 YAML 配置文件加载为普通字典。"""

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigurationError(f"Config file does not exist: {config_path}")

    content = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(content, dict):
        raise ConfigurationError("Top-level config must be a YAML mapping.")

    return content


def load_config(path: str | Path) -> AppConfig:
    """加载、展开、校验并规范化 CertKeeper 配置。"""

    config_path = Path(path)
    expanded = _expand_env_values(load_raw_config(config_path))
    errors: list[str] = []

    acme_section = expanded.get("acme")
    if not isinstance(acme_section, dict):
        errors.append("The 'acme' section is required and must be a mapping.")
        acme_section = {}

    certificates_section = expanded.get("certificates", [])
    if not isinstance(certificates_section, list):
        errors.append("The 'certificates' section must be a list.")
        certificates_section = []

    scheduler_section = expanded.get("scheduler", {})
    if not isinstance(scheduler_section, dict):
        errors.append("The 'scheduler' section must be a mapping.")
        scheduler_section = {}

    web_ui_section = expanded.get("web_ui", {})
    if not isinstance(web_ui_section, dict):
        errors.append("The 'web_ui' section must be a mapping.")
        web_ui_section = {}

    notifications = _load_named_resources("notifications", expanded.get("notifications", {}), errors)
    dns_providers = _load_named_resources("dns_providers", expanded.get("dns_providers", {}), errors)
    deployers = _load_named_resources("deployers", expanded.get("deployers", {}), errors)

    certificates: list[CertificateConfig] = []
    for index, item in enumerate(certificates_section):
        if not isinstance(item, dict):
            errors.append(f"certificates[{index}] must be a mapping.")
            continue

        domain = str(item.get("domain", "")).strip()
        challenge = str(item.get("challenge", "")).strip()
        san = item.get("san", [])
        deploy_to = item.get("deploy_to", [])
        dns_provider = item.get("dns_provider")
        http_root = item.get("http_root")

        if not domain:
            errors.append(f"certificates[{index}] is missing 'domain'.")
        if challenge not in {"dns-01", "http-01"}:
            errors.append(f"certificates[{index}] has unsupported challenge '{challenge}'.")
        if san and not isinstance(san, list):
            errors.append(f"certificates[{index}].san must be a list.")
            san = []
        if not isinstance(deploy_to, list):
            errors.append(f"certificates[{index}].deploy_to must be a list.")
            deploy_to = []

        if challenge == "dns-01":
            if not dns_provider:
                errors.append(f"certificates[{index}] uses dns-01 but is missing 'dns_provider'.")
            elif str(dns_provider) not in dns_providers:
                errors.append(f"certificates[{index}] references unknown dns provider '{dns_provider}'.")

        if challenge == "http-01" and not http_root:
            errors.append(f"certificates[{index}] uses http-01 but is missing 'http_root'.")

        for target in deploy_to:
            if str(target) not in deployers:
                errors.append(f"certificates[{index}] references unknown deploy target '{target}'.")

        certificates.append(
            CertificateConfig(
                domain=domain,
                san=[str(entry) for entry in san],
                challenge=challenge,
                dns_provider=str(dns_provider) if dns_provider else None,
                http_root=str(http_root) if http_root else None,
                deploy_to=[str(entry) for entry in deploy_to],
            )
        )

    account_key = str(acme_section.get("account_key", "./data/account.key"))
    acme = AcmeConfig(
        directory=str(acme_section.get("directory", "")).strip(),
        email=str(acme_section.get("email", "")).strip(),
        account_key=account_key,
    )

    if not acme.directory:
        errors.append("The 'acme.directory' value is required.")
    if not acme.email:
        errors.append("The 'acme.email' value is required.")

    web_ui = WebUiConfig(
        enabled=bool(web_ui_section.get("enabled", False)),
        host=str(web_ui_section.get("host", "127.0.0.1")).strip(),
        port=int(web_ui_section.get("port", 8080)),
        base_url=str(web_ui_section.get("base_url", f"http://127.0.0.1:{int(web_ui_section.get('port', 8080))}")).strip(),
        session_secret=_optional_string(web_ui_section.get("session_secret")),
        admin_username=_optional_string(web_ui_section.get("admin_username")),
        admin_password_hash=_optional_string(web_ui_section.get("admin_password_hash")),
    )

    if web_ui.enabled:
        if not web_ui.session_secret:
            errors.append("The 'web_ui.session_secret' value is required when web_ui is enabled.")
        if not web_ui.admin_username:
            errors.append("The 'web_ui.admin_username' value is required when web_ui is enabled.")
        if not web_ui.admin_password_hash:
            errors.append("The 'web_ui.admin_password_hash' value is required when web_ui is enabled.")

    if errors:
        raise ConfigurationError("; ".join(errors))

    return AppConfig(
        path=config_path,
        acme=acme,
        scheduler=SchedulerConfig(
            enabled=bool(scheduler_section.get("enabled", True)),
            interval=str(scheduler_section.get("interval", "daily")),
            time=str(scheduler_section.get("time", "03:00")),
            reminder_days=int(scheduler_section.get("reminder_days", 30)),
            renewal_days=int(scheduler_section.get("renewal_days", 30)),
        ),
        web_ui=web_ui,
        notifications=notifications,
        dns_providers=dns_providers,
        deployers=deployers,
        certificates=certificates,
    )


def _expand_env_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_values(item) for item in value]
    if isinstance(value, str):
        return ENV_VAR_PATTERN.sub(_replace_env_match, value)
    return value


def _replace_env_match(match: re.Match[str]) -> str:
    env_name = match.group(1)
    env_value = os.getenv(env_name)
    if env_value is None:
        raise ConfigurationError(f"Missing required environment variable: {env_name}")
    return env_value


def _load_named_resources(section_name: str, section: Any, errors: list[str]) -> dict[str, NamedResourceConfig]:
    if section in (None, {}):
        return {}
    if not isinstance(section, dict):
        errors.append(f"The '{section_name}' section must be a mapping.")
        return {}

    resources: dict[str, NamedResourceConfig] = {}
    for name, raw in section.items():
        if not isinstance(raw, dict):
            errors.append(f"{section_name}.{name} must be a mapping.")
            continue

        resource_type = str(raw.get("type", "")).strip()
        if not resource_type:
            errors.append(f"{section_name}.{name} is missing 'type'.")
            continue

        settings = {key: value for key, value in raw.items() if key != "type"}
        resources[str(name)] = NamedResourceConfig(name=str(name), type=resource_type, settings=settings)

    return resources


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")


def validate_domain(domain: str) -> str | None:
    """校验域名格式，返回错误信息或 None。"""
    domain = domain.strip()
    if not domain:
        return "域名不能为空。"
    if len(domain) > 253:
        return "域名长度不能超过 253 个字符。"
    if not DOMAIN_RE.match(domain):
        return "域名格式不正确。"
    return None


def save_config(config: AppConfig, *, include_resources: bool = False, include_scheduler: bool = False) -> None:
    """将配置写回 YAML 文件。

    默认只更新 certificates 部分。设置 include_resources=True 时
    同时更新 deployers 和 dns_providers。设置 include_scheduler=True 时
    同时更新 scheduler 部分。
    """
    raw = load_raw_config(config.path)
    raw["certificates"] = [_cert_to_dict(c) for c in config.certificates]
    if include_resources:
        raw["deployers"] = _named_resources_to_dict(config.deployers)
        raw["dns_providers"] = _named_resources_to_dict(config.dns_providers)
    if include_scheduler:
        raw_scheduler = raw.get("scheduler", {})
        if not isinstance(raw_scheduler, dict):
            raw_scheduler = {}
        raw_scheduler.update(_scheduler_to_dict(config.scheduler))
        raw["scheduler"] = raw_scheduler
    config.path.write_text(
        yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _named_resources_to_dict(resources: dict[str, NamedResourceConfig]) -> dict[str, Any]:
    """将 NamedResourceConfig 映射序列化为 YAML 友好的字典。"""
    result: dict[str, Any] = {}
    for name, res in resources.items():
        entry: dict[str, Any] = {"type": res.type}
        entry.update(res.settings)
        result[name] = entry
    return result


def _scheduler_to_dict(scheduler: SchedulerConfig) -> dict[str, Any]:
    """将 SchedulerConfig 序列化为 YAML 友好的字典。"""
    d: dict[str, Any] = {
        "enabled": scheduler.enabled,
        "interval": scheduler.interval,
        "time": scheduler.time,
        "reminder_days": scheduler.reminder_days,
        "renewal_days": scheduler.renewal_days,
    }
    return d


def _cert_to_dict(cert: CertificateConfig) -> dict[str, Any]:
    """将 CertificateConfig 序列化为 YAML 友好的字典。"""
    d: dict[str, Any] = {
        "domain": cert.domain,
        "challenge": cert.challenge,
        "deploy_to": cert.deploy_to,
    }
    if cert.san:
        d["san"] = cert.san
    if cert.dns_provider:
        d["dns_provider"] = cert.dns_provider
    if cert.http_root:
        d["http_root"] = cert.http_root
    return d


__all__ = [
    "AcmeConfig",
    "AppConfig",
    "CertificateConfig",
    "ConfigurationError",
    "NamedResourceConfig",
    "SchedulerConfig",
    "WebUiConfig",
    "load_config",
    "load_raw_config",
    "save_config",
    "validate_domain",
]
