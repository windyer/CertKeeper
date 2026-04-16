from __future__ import annotations

from fastapi.testclient import TestClient

from certkeeper.web.app import create_app
from certkeeper.web.auth import hash_password


def _make_config(tmp_path, monkeypatch, *, with_providers: bool = False) -> tuple[TestClient, str]:
    """创建带认证的测试客户端，返回 (client, csrf_token)。"""
    monkeypatch.setenv("WEB_SESSION_SECRET", "super-secret")
    password_hash = hash_password("admin123", salt="testsalt", iterations=1000)

    providers_section = ""
    if with_providers:
        providers_section = "\n".join([
            "dns_providers:",
            "  test-dns:",
            "    type: aliyun",
            "    access_key: test",
            "    secret_key: test",
            "deployers:",
            "  test-deploy:",
            "    type: nginx-ssh",
            "    host: 127.0.0.1",
        ])

    config_file = tmp_path / "certkeeper.yaml"
    config_file.write_text(
        "\n".join([
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
            providers_section,
        ]),
        encoding="utf-8",
    )

    app = create_app(config_file)
    client = TestClient(app)

    login_page = client.get("/login")
    csrf_token = _extract_csrf(login_page.text)
    client.post("/login", data={
        "username": "admin", "password": "admin123", "csrf_token": csrf_token,
    })
    return client, csrf_token


def _extract_csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


def test_new_certificate_page_renders(tmp_path, monkeypatch) -> None:
    client, _ = _make_config(tmp_path, monkeypatch)
    response = client.get("/certificates/new")
    assert response.status_code == 200
    assert "新增证书" in response.text


def test_create_certificate_success(tmp_path, monkeypatch) -> None:
    client, csrf_token = _make_config(tmp_path, monkeypatch, with_providers=True)
    response = client.post("/certificates", data={
        "csrf_token": csrf_token,
        "domain": "example.com",
        "challenge": "dns-01",
        "dns_provider": "test-dns",
        "deploy_to": "test-deploy",
    }, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"

    # Verify certificate appears on dashboard
    dashboard = client.get("/")
    assert "example.com" in dashboard.text


def test_create_certificate_rejects_duplicate_domain(tmp_path, monkeypatch) -> None:
    client, csrf_token = _make_config(tmp_path, monkeypatch, with_providers=True)
    # Create first
    client.post("/certificates", data={
        "csrf_token": csrf_token,
        "domain": "example.com",
        "challenge": "dns-01",
        "dns_provider": "test-dns",
        "deploy_to": "test-deploy",
    }, follow_redirects=False)
    # Create duplicate
    response = client.post("/certificates", data={
        "csrf_token": csrf_token,
        "domain": "example.com",
        "challenge": "dns-01",
        "dns_provider": "test-dns",
        "deploy_to": "test-deploy",
    }, follow_redirects=False)
    assert response.status_code == 400
    assert "已存在" in response.text


def test_edit_certificate_page_renders(tmp_path, monkeypatch) -> None:
    client, csrf_token = _make_config(tmp_path, monkeypatch, with_providers=True)
    # Create first
    client.post("/certificates", data={
        "csrf_token": csrf_token,
        "domain": "example.com",
        "challenge": "dns-01",
        "dns_provider": "test-dns",
        "deploy_to": "test-deploy",
    }, follow_redirects=False)
    # Get edit page
    response = client.get("/certificates/example.com/edit")
    assert response.status_code == 200
    assert "编辑证书" in response.text
    assert "readonly" in response.text


def test_update_certificate_success(tmp_path, monkeypatch) -> None:
    client, csrf_token = _make_config(tmp_path, monkeypatch, with_providers=True)
    # Create
    client.post("/certificates", data={
        "csrf_token": csrf_token,
        "domain": "example.com",
        "challenge": "dns-01",
        "dns_provider": "test-dns",
        "deploy_to": "test-deploy",
    }, follow_redirects=False)
    # Update
    response = client.post("/certificates/example.com", data={
        "csrf_token": csrf_token,
        "domain": "example.com",
        "challenge": "http-01",
        "http_root": "/var/www/html",
    }, follow_redirects=False)
    assert response.status_code == 302


def test_delete_certificate_success(tmp_path, monkeypatch) -> None:
    client, csrf_token = _make_config(tmp_path, monkeypatch, with_providers=True)
    # Create
    client.post("/certificates", data={
        "csrf_token": csrf_token,
        "domain": "example.com",
        "challenge": "dns-01",
        "dns_provider": "test-dns",
        "deploy_to": "test-deploy",
    }, follow_redirects=False)
    # Delete
    response = client.post("/certificates/example.com/delete", data={
        "csrf_token": csrf_token,
    }, follow_redirects=False)
    assert response.status_code == 302

    dashboard = client.get("/")
    # Certificate should no longer appear in the cert list (check the list items, not flash)
    assert "暂无证书配置" in dashboard.text


def test_crud_routes_require_login(tmp_path, monkeypatch) -> None:
    client, _ = _make_config(tmp_path, monkeypatch)
    # Clear session
    client.cookies.clear()

    assert client.get("/certificates/new", follow_redirects=False).status_code == 302
    assert client.post("/certificates", follow_redirects=False).status_code == 302
    assert client.get("/certificates/x/edit", follow_redirects=False).status_code == 302
    assert client.post("/certificates/x", follow_redirects=False).status_code == 302
    assert client.post("/certificates/x/delete", follow_redirects=False).status_code == 302
