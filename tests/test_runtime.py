from __future__ import annotations

from certkeeper.runtime import build_runtime


def test_build_runtime_returns_manager_and_store(tmp_path, monkeypatch) -> None:
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
                "  host: 127.0.0.1",
                "  port: 8080",
                "  session_secret: ${WEB_SESSION_SECRET}",
                "  admin_username: admin",
                "  admin_password_hash: pbkdf2_sha256$600000$salt$hash",
                "certificates: []",
            ]
        ),
        encoding="utf-8",
    )

    runtime = build_runtime(config_file)

    assert runtime.config.path == config_file
    assert runtime.manager is not None
    assert runtime.store.base_path == tmp_path / "data"
