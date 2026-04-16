# 证书配置管理 UI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Web UI 中添加证书配置的完整 CRUD 功能，用户可以在界面上新增、查看、编辑、删除证书配置。

**Architecture:** 复用现有 FastAPI + Jinja2 架构。在 config.py 新增 `save_config()` 函数将配置写回 YAML 文件，routes.py 新增 5 个 CRUD 路由，新增 `certificate_form.html` 表单模板，修改 `dashboard.html` 添加操作按钮。

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, PyYAML, vanilla JavaScript

---

### Task 1: config.py — save_config 与 domain 校验

**Files:**
- Modify: `certkeeper/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 在 `certkeeper/config.py` 末尾（`__all__` 之前）添加以下代码**

```python
DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")


def validate_domain(domain: str) -> str | None:
    """校验域名格式，返回错误信息或 None。"""
    domain = domain.strip()
    if not domain:
        return "域名不能为空。"
    if len(domain) > 253:
        return "域名长度不能超过 253 个字符。"
    if not DOMAIN_RE.match(domain):
        return "域名格式不正确。"
    return None


def save_config(config: AppConfig) -> None:
    """将配置写回 YAML 文件，只更新 certificates 部分。"""
    raw = load_raw_config(config.path)
    raw["certificates"] = [_cert_to_dict(c) for c in config.certificates]
    config.path.write_text(
        yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _cert_to_dict(cert: CertificateConfig) -> dict[str, Any]:
    """将 CertificateConfig 序列化为 YAML 友好的字典。"""
    d: dict[str, Any] = {
        "domain": cert.domain,
        "challenge": cert.challenge,
        "deploy_to": cert.deploy_to,
    }
    if cert.san:
        d["san"] = cert.san
    if cert.dns_provider:
        d["dns_provider"] = cert.dns_provider
    if cert.http_root:
        d["http_root"] = cert.http_root
    return d
```

更新 `__all__` 列表，添加 `"save_config"` 和 `"validate_domain"`。

- [ ] **Step 2: 在 `tests/test_config.py` 末尾添加测试**

```python
from certkeeper.config import save_config, validate_domain


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
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd C:/Users/windy/CertKeeper && python -m pytest tests/test_config.py -v`
Expected: 所有测试 PASS

- [ ] **Step 4: 提交**

```bash
git add certkeeper/config.py tests/test_config.py
git commit -m "feat(config): 添加 save_config 写回 YAML 和 validate_domain 域名校验"
```

---

### Task 2: base.html — 添加表单相关 CSS

**Files:**
- Modify: `certkeeper/web/templates/base.html`

- [ ] **Step 1: 在 `base.html` 的 `<style>` 标签内、`@media` 规则之前添加以下 CSS**

```css
    .form-group { margin-bottom: 1rem; }
    select {
      width: 100%;
      max-width: 20rem;
      padding: 0.5rem 0.75rem;
      border: 1px solid var(--border);
      border-radius: 0.375rem;
      font-size: 0.875rem;
      color: var(--text);
      background: var(--surface);
    }
    select:focus {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
    }
    .san-row {
      display: flex;
      gap: 0.5rem;
      margin-bottom: 0.5rem;
      align-items: center;
    }
    .san-row input { flex: 1; max-width: 20rem; }
    .btn-remove {
      padding: 0.25rem 0.5rem;
      background: var(--danger);
      color: #fff;
      border: none;
      border-radius: 0.375rem;
      cursor: pointer;
      font-size: 0.875rem;
      line-height: 1;
    }
    .btn-remove:hover { background: #b91c1c; }
    .btn-secondary {
      background: var(--surface);
      color: var(--text);
      border: 1px solid var(--border);
    }
    .btn-secondary:hover { background: var(--bg); }
    .checkbox-label {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.25rem;
      font-size: 0.875rem;
      font-weight: normal;
      color: var(--text);
      cursor: pointer;
    }
    .checkbox-label input[type="checkbox"] { width: auto; margin: 0; }
    input[readonly] { background: var(--bg); color: var(--text-muted); cursor: not-allowed; }
    .text-muted { color: var(--text-muted); font-size: 0.875rem; margin-top: 0.25rem; }
    .form-actions { display: flex; gap: 0.5rem; margin-top: 1.5rem; }
    .cert-item-actions { display: inline-flex; gap: 0.25rem; margin-left: 0.5rem; }
    .cert-item-actions form { display: inline; }
    .cert-item-actions button {
      padding: 0.25rem 0.5rem;
      font-size: 0.75rem;
    }
    .btn-danger { background: var(--danger); }
    .btn-danger:hover { background: #b91c1c; }
    .btn-small {
      padding: 0.25rem 0.5rem;
      font-size: 0.75rem;
    }
    .cert-list-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.75rem;
    }
```

- [ ] **Step 2: 提交**

```bash
git add certkeeper/web/templates/base.html
git commit -m "style(base): 添加表单、按钮、动态列表等 CSS 样式"
```

---

### Task 3: certificate_form.html — 创建表单模板

**Files:**
- Create: `certkeeper/web/templates/certificate_form.html`

- [ ] **Step 1: 创建 `certkeeper/web/templates/certificate_form.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>{{ title }}</h1>

{% if errors %}
<div class="error-msg">
  <ul style="margin:0;padding-left:1.25rem;">
  {% for err in errors %}
    <li>{{ err }}</li>
  {% endfor %}
  </ul>
</div>
{% endif %}

<form method="post" action="{{ form_action }}">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">

  <div class="form-group">
    <label>主域名</label>
    <input type="text" name="domain" value="{{ form_data.domain }}"
           {% if editing %}readonly{% endif %}
           placeholder="example.com">
  </div>

  <div class="form-group">
    <label>验证方式</label>
    <select name="challenge" id="challenge-select">
      <option value="dns-01" {% if form_data.challenge == "dns-01" %}selected{% endif %}>DNS-01</option>
      <option value="http-01" {% if form_data.challenge == "http-01" %}selected{% endif %}>HTTP-01</option>
    </select>
  </div>

  <div id="dns-fields" class="challenge-fields">
    <div class="form-group">
      <label>DNS 提供商</label>
      <select name="dns_provider">
        <option value="">-- 请选择 --</option>
        {% for name in dns_providers %}
        <option value="{{ name }}" {% if form_data.dns_provider == name %}selected{% endif %}>{{ name }}</option>
        {% endfor %}
      </select>
      {% if not dns_providers %}
      <p class="text-muted">暂无 DNS 提供商，请先在配置文件中添加 dns_providers。</p>
      {% endif %}
    </div>
  </div>

  <div id="http-fields" class="challenge-fields">
    <div class="form-group">
      <label>HTTP 根路径</label>
      <input type="text" name="http_root" value="{{ form_data.http_root }}"
             placeholder="/var/www/html">
    </div>
  </div>

  <div class="form-group">
    <label>备用域名 (SAN，可选)</label>
    <div id="san-list">
      {% for s in form_data.san %}
      <div class="san-row">
        <input type="text" name="san" value="{{ s }}" placeholder="www.example.com">
        <button type="button" class="btn-remove" onclick="removeSanRow(this)">×</button>
      </div>
      {% endfor %}
    </div>
    <button type="button" class="btn btn-secondary btn-small" onclick="addSanRow()">+ 添加备用域名</button>
  </div>

  <div class="form-group">
    <label>部署目标</label>
    {% if deployers %}
      {% for name in deployers %}
      <label class="checkbox-label">
        <input type="checkbox" name="deploy_to" value="{{ name }}"
               {% if name in form_data.deploy_to %}checked{% endif %}>
        {{ name }}
      </label>
      {% endfor %}
    {% else %}
      <p class="text-muted">暂无部署目标，请先在配置文件中添加 deployers。保存后可稍后编辑添加。</p>
    {% endif %}
  </div>

  <div class="form-actions">
    <button type="submit">保存</button>
    <a href="/" class="btn btn-secondary">取消</a>
  </div>
</form>

<script>
function toggleChallengeFields() {
  var val = document.getElementById("challenge-select").value;
  document.getElementById("dns-fields").style.display = val === "dns-01" ? "block" : "none";
  document.getElementById("http-fields").style.display = val === "http-01" ? "block" : "none";
}
toggleChallengeFields();
document.getElementById("challenge-select").addEventListener("change", toggleChallengeFields);

function addSanRow() {
  var container = document.getElementById("san-list");
  var row = document.createElement("div");
  row.className = "san-row";
  row.innerHTML = '<input type="text" name="san" placeholder="www.example.com"><button type="button" class="btn-remove" onclick="removeSanRow(this)">×</button>';
  container.appendChild(row);
}

function removeSanRow(btn) {
  btn.parentElement.remove();
}
</script>
{% endblock %}
```

- [ ] **Step 2: 提交**

```bash
git add certkeeper/web/templates/certificate_form.html
git commit -m "feat(web): 添加证书配置表单模板 certificate_form.html"
```

---

### Task 4: routes.py — CRUD 路由

**Files:**
- Modify: `certkeeper/web/routes.py`

- [ ] **Step 1: 在 `routes.py` 顶部添加新的 import**

在现有的 import 区域后添加：

```python
from certkeeper.config import AppConfig, CertificateConfig, save_config, validate_domain
from certkeeper.runtime import build_runtime
```

- [ ] **Step 2: 在 `register_routes` 函数末尾、`_resolve_path` 函数之前，添加辅助函数**

在 `register_routes` 函数内部、`@app.post("/actions/deploy/{domain}")` 路由之后，添加以下辅助函数（仍在 `register_routes` 函数体内）：

```python
    def _reload_runtime(app: FastAPI) -> None:
        """保存配置后重新构建运行时。"""
        app.state.runtime = build_runtime(app.state.config_path)

    def _cert_form_context(
        request: Request, *, editing: bool = False,
        form_data: dict | None = None, errors: list[str] | None = None,
        title: str = "新增证书", form_action: str = "/certificates",
    ) -> dict:
        """构建证书表单模板上下文。"""
        config = request.app.state.runtime.config
        return {
            "title": title,
            "csrf_token": ensure_csrf_token(request.session),
            "form_data": form_data or {
                "domain": "", "challenge": "dns-01",
                "dns_provider": "", "http_root": "", "san": [], "deploy_to": [],
            },
            "errors": errors or [],
            "dns_providers": list(config.dns_providers.keys()),
            "deployers": list(config.deployers.keys()),
            "editing": editing,
            "form_action": form_action,
        }

    def _validate_cert_form(
        domain: str, challenge: str, dns_provider: str, http_root: str,
        deploy_to: list[str], config: "AppConfig", *, is_new: bool = True,
    ) -> list[str]:
        """校验证书表单数据，返回错误列表。"""
        errors: list[str] = []
        domain_err = validate_domain(domain)
        if domain_err:
            errors.append(domain_err)
        if is_new and domain.strip() in [c.domain for c in config.certificates]:
            errors.append(f"域名 {domain.strip()} 已存在。")
        if challenge not in ("dns-01", "http-01"):
            errors.append("请选择验证方式。")
        if challenge == "dns-01" and not dns_provider.strip():
            errors.append("DNS-01 验证需要选择 DNS 提供商。")
        if challenge == "http-01" and not http_root.strip():
            errors.append("HTTP-01 验证需要填写 HTTP 根路径。")
        if deploy_to and config.deployers:
            for target in deploy_to:
                if target not in config.deployers:
                    errors.append(f"未知的部署目标: {target}")
        return errors
```

- [ ] **Step 3: 在 `register_routes` 函数内添加 CRUD 路由**

在辅助函数之后添加以下路由：

```python
    # ── 证书配置 CRUD ──

    @app.get("/certificates/new", response_class=HTMLResponse)
    async def new_certificate(request: Request):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        return templates.TemplateResponse(
            request, "certificate_form.html",
            _cert_form_context(request, title="新增证书"),
        )

    @app.post("/certificates")
    async def create_certificate(request: Request):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        form = await request.form()
        csrf_token = str(form.get("csrf_token", ""))
        validate_csrf(request, csrf_token)

        domain = str(form.get("domain", "")).strip()
        challenge = str(form.get("challenge", "")).strip()
        dns_provider = str(form.get("dns_provider", "")).strip()
        http_root = str(form.get("http_root", "")).strip()
        san = [str(v).strip() for v in form.getlist("san") if str(v).strip()]
        deploy_to = [str(v).strip() for v in form.getlist("deploy_to") if str(v).strip()]

        config = request.app.state.runtime.config
        errors = _validate_cert_form(
            domain, challenge, dns_provider, http_root, deploy_to, config, is_new=True,
        )

        if errors:
            return templates.TemplateResponse(
                request, "certificate_form.html",
                _cert_form_context(
                    request,
                    form_data={
                        "domain": domain, "challenge": challenge,
                        "dns_provider": dns_provider, "http_root": http_root,
                        "san": san, "deploy_to": deploy_to,
                    },
                    errors=errors, title="新增证书",
                ),
                status_code=400,
            )

        cert = CertificateConfig(
            domain=domain, san=san, challenge=challenge,
            dns_provider=dns_provider or None,
            http_root=http_root or None,
            deploy_to=deploy_to,
        )
        config.certificates.append(cert)
        save_config(config)
        _reload_runtime(request.app)

        request.session["flash"] = f"证书 {domain} 已添加。"
        return RedirectResponse(url="/", status_code=302)

    @app.get("/certificates/{domain}/edit", response_class=HTMLResponse)
    async def edit_certificate(request: Request, domain: str):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        config = request.app.state.runtime.config
        cert = next((c for c in config.certificates if c.domain == domain), None)
        if cert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在。")

        return templates.TemplateResponse(
            request, "certificate_form.html",
            _cert_form_context(
                request, editing=True, title=f"编辑证书 {domain}",
                form_action=f"/certificates/{domain}",
                form_data={
                    "domain": cert.domain, "challenge": cert.challenge,
                    "dns_provider": cert.dns_provider or "",
                    "http_root": cert.http_root or "",
                    "san": cert.san, "deploy_to": cert.deploy_to,
                },
            ),
        )

    @app.post("/certificates/{domain}")
    async def update_certificate(request: Request, domain: str):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        form = await request.form()
        csrf_token = str(form.get("csrf_token", ""))
        validate_csrf(request, csrf_token)

        config = request.app.state.runtime.config
        cert = next((c for c in config.certificates if c.domain == domain), None)
        if cert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在。")

        challenge = str(form.get("challenge", "")).strip()
        dns_provider = str(form.get("dns_provider", "")).strip()
        http_root = str(form.get("http_root", "")).strip()
        san = [str(v).strip() for v in form.getlist("san") if str(v).strip()]
        deploy_to = [str(v).strip() for v in form.getlist("deploy_to") if str(v).strip()]

        errors = _validate_cert_form(
            domain, challenge, dns_provider, http_root, deploy_to, config, is_new=False,
        )

        if errors:
            return templates.TemplateResponse(
                request, "certificate_form.html",
                _cert_form_context(
                    request, editing=True, title=f"编辑证书 {domain}",
                    form_action=f"/certificates/{domain}",
                    form_data={
                        "domain": domain, "challenge": challenge,
                        "dns_provider": dns_provider, "http_root": http_root,
                        "san": san, "deploy_to": deploy_to,
                    },
                    errors=errors,
                ),
                status_code=400,
            )

        cert.challenge = challenge
        cert.san = san
        cert.dns_provider = dns_provider or None
        cert.http_root = http_root or None
        cert.deploy_to = deploy_to
        save_config(config)
        _reload_runtime(request.app)

        request.session["flash"] = f"证书 {domain} 已更新。"
        return RedirectResponse(url="/", status_code=302)

    @app.post("/certificates/{domain}/delete")
    async def delete_certificate(request: Request, domain: str):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        form = await request.form()
        csrf_token = str(form.get("csrf_token", ""))
        validate_csrf(request, csrf_token)

        config = request.app.state.runtime.config
        original_len = len(config.certificates)
        config.certificates = [c for c in config.certificates if c.domain != domain]
        if len(config.certificates) == original_len:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在。")
        save_config(config)
        _reload_runtime(request.app)

        request.session["flash"] = f"证书 {domain} 已删除。"
        return RedirectResponse(url="/", status_code=302)
```

- [ ] **Step 4: 运行现有测试确认无回归**

Run: `cd C:/Users/windy/CertKeeper && python -m pytest tests/ -v`
Expected: 所有现有测试 PASS

- [ ] **Step 5: 提交**

```bash
git add certkeeper/web/routes.py
git commit -m "feat(web): 添加证书配置 CRUD 路由（新增/编辑/更新/删除）"
```

---

### Task 5: dashboard.html — 添加操作按钮

**Files:**
- Modify: `certkeeper/web/templates/dashboard.html`

- [ ] **Step 1: 替换 `dashboard.html` 全部内容**

```html
{% extends "base.html" %}
{% block content %}
<h1>证书概览</h1>
{% if flash %}
<p class="flash flash-success">{{ flash }}</p>
{% endif %}

<div class="cert-list-header">
  <form method="post" action="/actions/apply" class="inline">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <button type="submit">执行 apply</button>
  </form>
  <a href="/certificates/new" class="btn btn-secondary">+ 新增证书</a>
</div>

{% if checks %}
<ul class="cert-list">
{% for item in checks %}
  <li>
    <a href="/certificates/{{ item.domain }}">{{ item.domain }}</a>
    状态={{ item.reason }}
    到期剩余={{ item.expiry_text }}
    <span class="cert-item-actions">
      <a href="/certificates/{{ item.domain }}/edit" class="btn btn-secondary btn-small">编辑</a>
      <form method="post" action="/certificates/{{ item.domain }}/delete" class="inline">
        <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
        <button type="submit" class="btn btn-danger btn-small">删除</button>
      </form>
    </span>
  </li>
{% endfor %}
</ul>
{% else %}
<div class="empty-state">
  <p>暂无证书配置。点击上方"新增证书"开始添加。</p>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: 提交**

```bash
git add certkeeper/web/templates/dashboard.html
git commit -m "feat(web): Dashboard 添加新增/编辑/删除证书按钮"
```

---

### Task 6: 集成测试

**Files:**
- Create: `tests/test_web_cert_crud.py`

- [ ] **Step 1: 创建测试文件 `tests/test_web_cert_crud.py`**

```python
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
    assert "example.com" not in dashboard.text


def test_crud_routes_require_login(tmp_path, monkeypatch) -> None:
    client, _ = _make_config(tmp_path, monkeypatch)
    # Clear session
    client.cookies.clear()

    assert client.get("/certificates/new", follow_redirects=False).status_code == 302
    assert client.post("/certificates", follow_redirects=False).status_code == 302
    assert client.get("/certificates/x/edit", follow_redirects=False).status_code == 302
    assert client.post("/certificates/x", follow_redirects=False).status_code == 302
    assert client.post("/certificates/x/delete", follow_redirects=False).status_code == 302
```

- [ ] **Step 2: 运行测试**

Run: `cd C:/Users/windy/CertKeeper && python -m pytest tests/test_web_cert_crud.py -v`
Expected: 所有测试 PASS

- [ ] **Step 3: 运行全部测试确认无回归**

Run: `cd C:/Users/windy/CertKeeper && python -m pytest tests/ -v`
Expected: 所有测试 PASS

- [ ] **Step 4: 提交**

```bash
git add tests/test_web_cert_crud.py
git commit -m "test(web): 添加证书配置 CRUD 路由集成测试"
```

---

### Task 7: 手动验证

- [ ] **Step 1: 启动 Web UI 服务器**

准备一个包含 dns_providers 和 deployers 的测试配置文件（如果 certkeeper.yaml 中没有的话），然后启动：

Run: `cd C:/Users/windy/CertKeeper && python -m certkeeper.web.app`

或通过 CLI：

Run: `cd C:/Users/windy/CertKeeper && python -m certkeeper.cli web --config certkeeper.yaml`

- [ ] **Step 2: 在浏览器中验证以下流程**

1. 访问 http://127.0.0.1:8088，登录
2. 点击"+ 新增证书"按钮
3. 填写域名、选择验证方式、选择部署目标，保存
4. 确认 Dashboard 上出现新证书
5. 点击"编辑"，修改配置，保存
6. 点击"删除"，确认证书被移除
7. 检查 certkeeper.yaml 文件内容是否正确更新
