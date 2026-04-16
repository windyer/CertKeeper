"""DNS-01 challenge 处理器。"""

from __future__ import annotations

from certkeeper.challenges.base import ChallengeHandler
from certkeeper.config import CertificateConfig, NamedResourceConfig
from certkeeper.dns.base import DnsProvider, ProviderRegistry


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
        provider.create_txt_record(
            domain,
            f"_acme-challenge.{domain}",
            validation,
        )

    def cleanup(self, certificate: CertificateConfig, validation: str = "") -> None:
        provider = self._resolve_provider(certificate)
        domain = certificate.domain.lstrip("*.")
        provider.delete_txt_record(
            domain,
            f"_acme-challenge.{domain}",
            validation,
        )

    def _resolve_provider(self, certificate: CertificateConfig) -> DnsProvider:
        if not certificate.dns_provider:
            raise ValueError("dns_provider is required for dns-01 challenges.")
        provider_config = self.dns_provider_configs[certificate.dns_provider]
        return self.provider_registry.create(provider_config)
