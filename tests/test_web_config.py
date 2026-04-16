from __future__ import annotations

import pytest

from certkeeper.config import ConfigurationError, load_config


def test_load_config_includes_web_ui_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WEB_SESSION_SECRET", "super-secret")
    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join(
            [
                "acme:",
                "  directory: https://acme-v02.api.letsencrypt.org/directory",
                "  email: admin@example.com",
                "  account_key: ./data/account.key",
                "web_ui:",
                "  enabled: true",
                "  host: 0.0.0.0",
                "  port: 8443",
                "  session_secret: ${WEB_SESSION_SECRET}",
                "  admin_username: admin",
                "  admin_password_hash: pbkdf2_sha256$600000$salt$hash",
                "certificates: []",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.web_ui.enabled is True
    assert config.web_ui.host == "0.0.0.0"
    assert config.web_ui.port == 8443
    assert config.web_ui.admin_username == "admin"


def test_public_web_ui_requires_secret_and_password_hash(tmp_path) -> None:
    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join(
            [
                "acme:",
                "  directory: https://acme-v02.api.letsencrypt.org/directory",
                "  email: admin@example.com",
                "  account_key: ./data/account.key",
                "web_ui:",
                "  enabled: true",
                "  host: 0.0.0.0",
                "  port: 8443",
                "  admin_username: admin",
                "certificates: []",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    message = str(exc_info.value)
    assert "session_secret" in message
    assert "admin_password_hash" in message
