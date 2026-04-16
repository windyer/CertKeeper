from __future__ import annotations

from fastapi.testclient import TestClient

from certkeeper.web.app import create_app
from certkeeper.web.auth import hash_password


def test_apply_action_requires_login_and_csrf(tmp_path, monkeypatch) -> None:
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

    assert client.post("/actions/apply", follow_redirects=False).status_code == 302

    login_page = client.get("/login")
    csrf_token = _extract_csrf(login_page.text)
    client.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": csrf_token})

    response = client.post("/actions/apply", data={"csrf_token": csrf_token}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/"


def _extract_csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]
