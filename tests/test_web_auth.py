from __future__ import annotations

from fastapi.testclient import TestClient

from certkeeper.web.app import create_app
from certkeeper.web.auth import hash_password


def test_login_allows_access_to_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WEB_SESSION_SECRET", "super-secret")
    password_hash = hash_password("admin123", salt="testsalt", iterations=1000)
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
                f"  admin_password_hash: {password_hash}",
                "certificates: []",
            ]
        ),
        encoding="utf-8",
    )

    app = create_app(config_file)
    client = TestClient(app)

    login_page = client.get("/login")
    assert login_page.status_code == 200
    csrf_token = _extract_csrf(login_page.text)

    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123", "csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "证书概览" in dashboard.text


def _extract_csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]
