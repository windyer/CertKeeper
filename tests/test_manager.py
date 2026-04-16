from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from certkeeper.config import (
    AcmeConfig,
    AppConfig,
    CertificateConfig,
    NamedResourceConfig,
    SchedulerConfig,
)
from certkeeper.core.manager import CertificateMaterial, Manager
from certkeeper.core.store import Store
from certkeeper.deployers.base import Deployer, ProviderRegistry
from certkeeper.notifications.base import Notifier


def _build_config(tmp_path) -> AppConfig:
    return AppConfig(
        path=tmp_path / "certkeeper.yaml",
        acme=AcmeConfig(
            directory="https://acme-v02.api.letsencrypt.org/directory",
            email="admin@example.com",
            account_key="./data/account.key",
        ),
        scheduler=SchedulerConfig(),
        notifications={
            "email": NamedResourceConfig(
                name="email",
                type="fake-email",
                settings={"recipient": "ops@example.com"},
            )
        },
        dns_providers={},
        deployers={
            "nginx-web": NamedResourceConfig(
                name="nginx-web",
                type="fake-deployer",
                settings={"host": "127.0.0.1"},
            )
        },
        certificates=[
            CertificateConfig(
                domain="example.com",
                san=["www.example.com"],
                challenge="http-01",
                dns_provider=None,
                http_root=str(tmp_path / "wwwroot"),
                deploy_to=["nginx-web"],
            )
        ],
    )


@dataclass
class FakeAcmeClient:
    requested_domains: list[str]

    def obtain_certificate(self, certificate, challenge_handler) -> CertificateMaterial:
        self.requested_domains.append(certificate.domain)
        challenge_handler.prepare(certificate)
        challenge_handler.cleanup(certificate)
        return CertificateMaterial(
            fullchain_pem="-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n",
            private_key_pem="-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
        )


@dataclass
class FakeChallengeHandler:
    prepared: list[str]

    def prepare(self, certificate) -> None:
        self.prepared.append(certificate.domain)

    def cleanup(self, certificate) -> None:
        self.prepared.append(f"cleanup:{certificate.domain}")


class FakeDeployer(Deployer):
    def validate_config(self) -> list[str]:
        return []

    def deploy(self, domain: str, cert_path, key_path):
        return {"domain": domain, "cert_path": str(cert_path), "key_path": str(key_path), "status": "success"}


class FakeNotifier(Notifier):
    def __init__(self, config):
        super().__init__(config)
        self.summaries = []

    def validate_config(self) -> list[str]:
        return []

    def notify(self, summary) -> None:
        self.summaries.append(summary)


def test_manager_apply_renews_and_deploys_when_certificate_missing(tmp_path) -> None:
    config = _build_config(tmp_path)
    store = Store(tmp_path / "data")
    acme_client = FakeAcmeClient(requested_domains=[])
    challenge_handler = FakeChallengeHandler(prepared=[])
    deployer_registry = ProviderRegistry(Deployer)
    deployer_registry.register("fake-deployer", FakeDeployer)
    notifier_registry = ProviderRegistry(Notifier)
    notifier_registry.register("fake-email", FakeNotifier)
    manager = Manager(
        config=config,
        store=store,
        acme_client=acme_client,
        challenge_handlers={"http-01": challenge_handler},
        deployer_registry=deployer_registry,
        notifier_registry=notifier_registry,
    )

    summary = manager.apply()

    assert summary.exit_code == 0
    assert acme_client.requested_domains == ["example.com"]
    assert challenge_handler.prepared == ["example.com", "cleanup:example.com"]
    assert summary.results[0].renewed is True
    assert summary.results[0].deployed_targets == ["nginx-web"]


def test_manager_check_marks_healthy_certificate_as_not_due(tmp_path) -> None:
    config = _build_config(tmp_path)
    store = Store(tmp_path / "data")
    store.save_certificate(
        "example.com",
        "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n",
        "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
    )
    store.record_result(
        domain="example.com",
        expires_at=datetime.now(UTC) + timedelta(days=90),
        renewed_at=datetime.now(UTC),
        deploy_results={"nginx-web": "success"},
    )
    manager = Manager(
        config=config,
        store=store,
        acme_client=FakeAcmeClient(requested_domains=[]),
        challenge_handlers={"http-01": FakeChallengeHandler(prepared=[])},
        deployer_registry=ProviderRegistry(Deployer),
        notifier_registry=ProviderRegistry(Notifier),
    )

    checks = manager.check_certificates()

    assert checks[0].domain == "example.com"
    assert checks[0].needs_renewal is False
    assert checks[0].reason == "healthy"


def test_manager_can_deploy_existing_healthy_certificate_without_renewal(tmp_path) -> None:
    config = _build_config(tmp_path)
    store = Store(tmp_path / "data")
    store.save_certificate(
        "example.com",
        "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----\n",
        "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
    )
    store.record_result(
        domain="example.com",
        expires_at=datetime.now(UTC) + timedelta(days=90),
        renewed_at=datetime.now(UTC),
        deploy_results={"nginx-web": "success"},
    )
    acme_client = FakeAcmeClient(requested_domains=[])
    deployer_registry = ProviderRegistry(Deployer)
    deployer_registry.register("fake-deployer", FakeDeployer)
    notifier_registry = ProviderRegistry(Notifier)
    notifier_registry.register("fake-email", FakeNotifier)
    manager = Manager(
        config=config,
        store=store,
        acme_client=acme_client,
        challenge_handlers={"http-01": FakeChallengeHandler(prepared=[])},
        deployer_registry=deployer_registry,
        notifier_registry=notifier_registry,
    )

    summary = manager.deploy("example.com")

    assert summary.exit_code == 0
    assert acme_client.requested_domains == []
    assert summary.results[0].renewed is False
    assert summary.results[0].deployed_targets == ["nginx-web"]
