import os

import pytest

from certkeeper.config import CertificateConfig, ConfigurationError, load_config, save_config, validate_domain


def test_load_config_expands_environment_variables_and_named_resources(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join(
            [
                "acme:",
                "  directory: https://acme-v02.api.letsencrypt.org/directory",
                "  email: admin@example.com",
                "  account_key: ./data/account.key",
                "notifications:",
                "  email:",
                "    type: smtp",
                "    host: smtp.example.com",
                "    password: ${SMTP_PASSWORD}",
                "dns_providers:",
                "  aliyun:",
                "    type: aliyun",
                "    access_key_id: demo",
                "    access_key_secret: secret",
                "deployers:",
                "  nginx-web:",
                "    type: nginx-ssh",
                "    host: 1.2.3.4",
                "    user: root",
                "    cert_path: /etc/nginx/ssl/",
                "    reload_command: systemctl reload nginx",
                "certificates:",
                "  - domain: example.com",
                "    san: [www.example.com]",
                "    challenge: dns-01",
                "    dns_provider: aliyun",
                "    deploy_to: [nginx-web]",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.notifications["email"].settings["password"] == "secret"
    assert config.certificates[0].dns_provider == "aliyun"
    assert config.certificates[0].san == ["www.example.com"]


def test_load_config_rejects_missing_named_references(tmp_path) -> None:
    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join(
            [
                "acme:",
                "  directory: https://acme-v02.api.letsencrypt.org/directory",
                "  email: admin@example.com",
                "  account_key: ./data/account.key",
                "deployers: {}",
                "certificates:",
                "  - domain: example.com",
                "    challenge: dns-01",
                "    dns_provider: aliyun",
                "    deploy_to: [missing-target]",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    assert "aliyun" in str(exc_info.value)
    assert "missing-target" in str(exc_info.value)


def test_load_config_requires_existing_environment_variable(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UNSET_SECRET", raising=False)
    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join(
            [
                "acme:",
                "  directory: https://acme-v02.api.letsencrypt.org/directory",
                "  email: admin@example.com",
                "  account_key: ./data/account.key",
                "notifications:",
                "  email:",
                "    type: smtp",
                "    password: ${UNSET_SECRET}",
                "certificates: []",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    assert "UNSET_SECRET" in str(exc_info.value)


def test_validate_domain_rejects_empty() -> None:
    assert validate_domain("") is not None


def test_validate_domain_rejects_slashes() -> None:
    assert validate_domain("../etc/passwd") is not None


def test_validate_domain_accepts_valid() -> None:
    assert validate_domain("example.com") is None
    assert validate_domain("sub.example.com") is None


def test_save_config_writes_certificates_to_yaml(tmp_path) -> None:
    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join(
            [
                "acme:",
                "  directory: https://acme-v02.api.letsencrypt.org/directory",
                "  email: admin@example.com",
                "  account_key: ./data/account.key",
                "dns_providers:",
                "  aliyun:",
                "    type: aliyun",
                "    access_key_id: demo",
                "    access_key_secret: secret",
                "deployers:",
                "  my-nginx:",
                "    type: nginx-ssh",
                "    host: 1.2.3.4",
                "certificates: []",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(config_file)
    config.certificates.append(
        CertificateConfig(
            domain="example.com",
            san=["www.example.com"],
            challenge="dns-01",
            dns_provider="aliyun",
            http_root=None,
            deploy_to=["my-nginx"],
        )
    )
    save_config(config)

    reloaded = load_config(config_file)
    assert len(reloaded.certificates) == 1
    assert reloaded.certificates[0].domain == "example.com"
    assert reloaded.certificates[0].san == ["www.example.com"]
    assert reloaded.certificates[0].challenge == "dns-01"
