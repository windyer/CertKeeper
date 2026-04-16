from __future__ import annotations

from certkeeper.challenges.dns01 import Dns01ChallengeHandler
from certkeeper.challenges.http01 import Http01ChallengeHandler
from certkeeper.config import CertificateConfig, NamedResourceConfig
from certkeeper.dns.base import DnsProvider, ProviderRegistry


class FakeDnsProvider(DnsProvider):
    all_records: list[tuple[str, str, str, str]] = []

    def __init__(self, config):
        super().__init__(config)

    def validate_config(self) -> list[str]:
        return []

    def create_txt_record(self, domain: str, name: str, value: str) -> None:
        self.all_records.append(("create", domain, name, value))

    def delete_txt_record(self, domain: str, name: str, value: str) -> None:
        self.all_records.append(("delete", domain, name, value))


def test_http01_handler_creates_challenge_directory(tmp_path) -> None:
    certificate = CertificateConfig(
        domain="example.com",
        san=[],
        challenge="http-01",
        dns_provider=None,
        http_root=str(tmp_path / "webroot"),
        deploy_to=[],
    )
    handler = Http01ChallengeHandler()

    handler.prepare(certificate)

    assert (tmp_path / "webroot" / ".well-known" / "acme-challenge").exists()


def test_dns01_handler_uses_named_provider_for_create_and_cleanup() -> None:
    FakeDnsProvider.all_records = []
    registry = ProviderRegistry(DnsProvider)
    registry.register("fake-dns", FakeDnsProvider)
    provider_config = NamedResourceConfig(name="aliyun", type="fake-dns", settings={})
    handler = Dns01ChallengeHandler(
        dns_provider_configs={"aliyun": provider_config},
        provider_registry=registry,
    )
    certificate = CertificateConfig(
        domain="example.com",
        san=[],
        challenge="dns-01",
        dns_provider="aliyun",
        http_root=None,
        deploy_to=[],
    )

    handler.prepare(certificate, validation="test-key-authz-value")
    handler.cleanup(certificate, validation="test-key-authz-value")

    assert FakeDnsProvider.all_records == [
        ("create", "example.com", "_acme-challenge.example.com", "test-key-authz-value"),
        ("delete", "example.com", "_acme-challenge.example.com", "test-key-authz-value"),
    ]


def test_dns01_handler_strips_wildcard_prefix() -> None:
    FakeDnsProvider.all_records = []
    registry = ProviderRegistry(DnsProvider)
    registry.register("fake-dns", FakeDnsProvider)
    provider_config = NamedResourceConfig(name="aliyun", type="fake-dns", settings={})
    handler = Dns01ChallengeHandler(
        dns_provider_configs={"aliyun": provider_config},
        provider_registry=registry,
    )
    certificate = CertificateConfig(
        domain="*.example.com",
        san=[],
        challenge="dns-01",
        dns_provider="aliyun",
        http_root=None,
        deploy_to=[],
    )

    handler.prepare(certificate, validation="abc")

    assert FakeDnsProvider.all_records[0][2] == "_acme-challenge.example.com"
