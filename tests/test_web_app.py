from __future__ import annotations

from fastapi.testclient import TestClient

from certkeeper.web.app import create_app


def test_dashboard_redirects_to_login_when_not_authenticated(tmp_path, monkeypatch) -> None:
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

    app = create_app(config_file)
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
