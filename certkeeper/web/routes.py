"""Web UI 路由。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from certkeeper.acme_client.account import AcmeAccountService
from certkeeper.config import (
    AppConfig,
    CertificateConfig,
    NamedResourceConfig,
    save_config,
    validate_domain,
)
from certkeeper.runtime import build_runtime
from certkeeper.web.auth import ensure_csrf_token, require_login, validate_csrf, verify_password
from certkeeper.web.resource_fields import (
    DEPLOYER_TYPES,
    DEPLOYER_TYPE_LABELS,
    DNS_PROVIDER_TYPES,
    DNS_PROVIDER_TYPE_LABELS,
    SENSITIVE_FIELDS,
)

logger = logging.getLogger(__name__)


def register_routes(app: FastAPI) -> None:
    """注册第一版 Web UI 路由。"""

    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        csrf_token = ensure_csrf_token(request.session)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"title": "登录", "csrf_token": csrf_token, "error": None},
        )

    @app.post("/login")
    async def login(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        csrf_token: str = Form(""),
    ):
        if not csrf_token:
            validate_csrf(request, None)
        else:
            validate_csrf(request, csrf_token)
        if not username or not password:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"title": "登录", "csrf_token": ensure_csrf_token(request.session), "error": "请输入用户名和密码。"},
                status_code=400,
            )
        web_ui = request.app.state.runtime.config.web_ui
        if username != web_ui.admin_username or not web_ui.admin_password_hash or not verify_password(password, web_ui.admin_password_hash):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"title": "登录", "csrf_token": ensure_csrf_token(request.session), "error": "用户名或密码错误。"},
                status_code=400,
            )

        request.session["authenticated"] = True
        request.session["username"] = username
        return RedirectResponse(url="/", status_code=302)

    @app.post("/logout")
    async def logout(request: Request, csrf_token: str | None = Form(None)):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        checks = request.app.state.runtime.manager.check_certificates()
        flash = request.session.pop("flash", None)
        csrf_token = ensure_csrf_token(request.session)
        check_items = [
            {
                "domain": item.domain,
                "reason": item.reason,
                "expiry_text": item.status.days_until_expiry if item.status.days_until_expiry is not None else "unknown",
            }
            for item in checks
        ]
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"title": "证书概览", "checks": check_items, "csrf_token": csrf_token, "flash": flash},
        )

    @app.get("/runtime", response_class=HTMLResponse)
    async def runtime_page(request: Request):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        runtime = request.app.state.runtime
        csrf_token = ensure_csrf_token(request.session)
        flash = request.session.pop("flash", None)

        scheduler_cfg = runtime.config.scheduler
        scheduler_obj = getattr(request.app.state, "scheduler", None)
        scheduler_running = scheduler_obj is not None and scheduler_obj.running

        jobs_info = []
        next_run = None
        if scheduler_running:
            for job in scheduler_obj.get_jobs():
                jobs_info.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time,
                })
                if job.next_run_time and (next_run is None or job.next_run_time < next_run):
                    next_run = job.next_run_time

        return templates.TemplateResponse(
            request,
            "runtime.html",
            {
                "title": "运行状态",
                "web_ui": runtime.config.web_ui,
                "scheduler": scheduler_cfg,
                "scheduler_running": scheduler_running,
                "jobs": jobs_info,
                "next_run": next_run,
                "csrf_token": csrf_token,
                "flash": flash,
            },
        )

    # ── 调度器管理 ──

    @app.post("/scheduler/update")
    async def scheduler_update(
        request: Request,
        enabled: str = Form("off"),
        interval: str = Form("daily"),
        time: str = Form("03:00"),
        reminder_days: str = Form("30"),
        csrf_token: str | None = Form(None),
    ):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)

        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        config = request.app.state.runtime.config
        scheduler_obj = getattr(request.app.state, "scheduler", None)

        # 更新配置
        config.scheduler.enabled = enabled == "on"
        config.scheduler.interval = interval
        config.scheduler.time = time
        try:
            config.scheduler.reminder_days = max(int(reminder_days), 1)
        except (ValueError, TypeError):
            config.scheduler.reminder_days = 30

        if scheduler_obj is not None and scheduler_obj.running:
            # 移除旧任务并重新添加
            scheduler_obj.remove_all_jobs()
            if config.scheduler.enabled:
                if config.scheduler.interval == "daily":
                    hour_text, minute_text = config.scheduler.time.split(":", maxsplit=1)
                    trigger = CronTrigger(hour=int(hour_text), minute=int(minute_text))
                else:
                    trigger = IntervalTrigger(days=1)

                def _scheduled_job():
                    request.app.state.runtime.manager.send_expiry_reminders()
                    request.app.state.runtime.manager.apply()

                scheduler_obj.add_job(
                    _scheduled_job,
                    trigger=trigger,
                    id="certkeeper-apply",
                    replace_existing=True,
                )
                request.session["flash"] = f"调度器配置已更新：{interval} {time}，提醒天数 {config.scheduler.reminder_days} 天"
            else:
                request.session["flash"] = "调度器已禁用，定时任务已清除。"
        else:
            request.session["flash"] = "调度器配置已保存（调度器未在当前进程中运行）。"

        return RedirectResponse(url="/runtime", status_code=302)

    @app.post("/scheduler/pause")
    async def scheduler_pause(request: Request, csrf_token: str | None = Form(None)):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)

        scheduler_obj = getattr(request.app.state, "scheduler", None)
        if scheduler_obj and scheduler_obj.running:
            scheduler_obj.pause()
            request.session["flash"] = "调度器已暂停。"
        else:
            request.session["flash"] = "调度器未运行。"
        return RedirectResponse(url="/runtime", status_code=302)

    @app.post("/scheduler/resume")
    async def scheduler_resume(request: Request, csrf_token: str | None = Form(None)):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)

        scheduler_obj = getattr(request.app.state, "scheduler", None)
        if scheduler_obj and scheduler_obj.running:
            scheduler_obj.resume()
            request.session["flash"] = "调度器已恢复。"
        else:
            request.session["flash"] = "调度器未运行。"
        return RedirectResponse(url="/runtime", status_code=302)

    @app.post("/scheduler/trigger")
    async def scheduler_trigger(request: Request, csrf_token: str | None = Form(None)):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)

        runtime = request.app.state.runtime
        try:
            summary = runtime.manager.apply()
            if summary.exit_code == 0:
                request.session["flash"] = "手动触发 apply 完成，所有证书处理成功。"
            else:
                errors = []
                for r in summary.results:
                    if r.errors:
                        errors.append(f"{r.domain}: {'; '.join(r.errors)}")
                request.session["flash"] = f"apply 部分失败：{' | '.join(errors)}"
        except Exception as exc:
            logger.exception("手动触发 apply 失败")
            request.session["flash"] = f"手动触发失败：{exc}"
        return RedirectResponse(url="/runtime", status_code=302)

    @app.post("/actions/register")
    async def register_account(request: Request, csrf_token: str | None = Form(None)):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)
        runtime = request.app.state.runtime
        account_service = AcmeAccountService()
        account_key_path = account_service.ensure_account_key(_resolve_path(request.app.state.config_path, runtime.config.acme.account_key))
        request.session["flash"] = f"ACME 账户密钥已准备：{account_key_path}"
        return RedirectResponse(url="/", status_code=302)

    @app.post("/actions/apply")
    async def apply_action(request: Request, csrf_token: str | None = Form(None)):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)
        summary = request.app.state.runtime.manager.apply()
        if summary.exit_code == 0:
            request.session["flash"] = "apply 完成，所有证书处理成功。"
        else:
            errors = []
            for r in summary.results:
                if r.errors:
                    errors.append(f"{r.domain}: {'; '.join(r.errors)}")
            request.session["flash"] = f"apply 部分失败：{' | '.join(errors)}"
        return RedirectResponse(url="/", status_code=302)

    @app.post("/actions/renew/{domain}")
    async def renew_action(request: Request, domain: str, csrf_token: str | None = Form(None)):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)
        summary = request.app.state.runtime.manager.apply(force=True, domain=domain)
        errors = [e for r in summary.results for e in r.errors]
        if errors:
            request.session["flash"] = f"renew {domain} 失败：{'; '.join(errors)}"
        else:
            request.session["flash"] = f"renew {domain} 完成。"
        return RedirectResponse(url="/", status_code=302)

    @app.post("/actions/deploy/{domain}")
    async def deploy_action(request: Request, domain: str, csrf_token: str | None = Form(None)):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        validate_csrf(request, csrf_token)
        summary = request.app.state.runtime.manager.deploy(domain=domain)
        errors = [e for r in summary.results for e in r.errors]
        if errors:
            request.session["flash"] = f"deploy {domain} 失败：{'; '.join(errors)}"
        else:
            request.session["flash"] = f"deploy {domain} 完成。"
        return RedirectResponse(url="/", status_code=302)

    # ── 证书配置 CRUD 辅助函数 ──

    def _reload_runtime(app: FastAPI) -> None:
        """保存配置后重新构建运行时。"""
        app.state.runtime = build_runtime(app.state.config_path)

    def _cert_form_context(
        request: Request, *, editing: bool = False,
        form_data: dict | None = None, errors: list[str] | None = None,
        title: str = "新增证书", form_action: str = "/certificates",
    ) -> dict:
        """构建证书表单模板上下文。"""
        import json as _json

        from certkeeper.web.resource_fields import (
            DEPLOYER_TYPES,
            DEPLOYER_TYPE_LABELS,
            DNS_PROVIDER_TYPES,
            DNS_PROVIDER_TYPE_LABELS,
        )

        config = request.app.state.runtime.config

        def _fields_schema(types: dict) -> list[dict]:
            return [
                {
                    "type": t,
                    "fields": [
                        {"name": f.name, "label": f.label, "secret": f.secret,
                         "required": f.required, "placeholder": f.placeholder}
                        for f in fields
                    ],
                }
                for t, fields in types.items()
            ]

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
            "deployer_type_labels": DEPLOYER_TYPE_LABELS,
            "dns_provider_type_labels": DNS_PROVIDER_TYPE_LABELS,
            "deployer_fields_json": _json.dumps(_fields_schema(DEPLOYER_TYPES)),
            "dns_provider_fields_json": _json.dumps(_fields_schema(DNS_PROVIDER_TYPES)),
        }

    def _validate_cert_form(
        domain: str, challenge: str, dns_provider: str, http_root: str,
        deploy_to: list[str], config: AppConfig, *, is_new: bool = True,
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

    @app.get("/certificates/{domain}", response_class=HTMLResponse)
    async def certificate_detail(request: Request, domain: str):
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        runtime = request.app.state.runtime
        certificate = next((item for item in runtime.config.certificates if item.domain == domain), None)
        if certificate is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="证书不存在。")
        csrf_token = ensure_csrf_token(request.session)
        return templates.TemplateResponse(
            request,
            "certificate_detail.html",
            {
                "title": domain,
                "certificate": certificate,
                "deploy_targets": ", ".join(certificate.deploy_to) or "-",
                "csrf_token": csrf_token,
            },
        )

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

    # ── 部署目标 API ──

    @app.get("/api/deployers")
    async def api_list_deployers(request: Request):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        config = request.app.state.runtime.config
        items = []
        for name, res in config.deployers.items():
            settings = dict(res.settings)
            for key in settings:
                if key in SENSITIVE_FIELDS:
                    settings[key] = "******"
            items.append({"name": name, "type": res.type, "settings": settings})
        return JSONResponse({"items": items, "types": DEPLOYER_TYPE_LABELS})

    @app.post("/api/deployers")
    async def api_create_deployer(request: Request):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        body = await request.json()
        csrf_token = body.get("csrf_token", "")
        validate_csrf(request, csrf_token)

        name = str(body.get("name", "")).strip()
        resource_type = str(body.get("type", "")).strip()
        settings = body.get("settings", {})

        errors = _validate_resource_fields(name, resource_type, settings, DEPLOYER_TYPES, is_new=True)
        config = request.app.state.runtime.config
        if name in config.deployers:
            errors.append(f"部署目标 '{name}' 已存在。")
        if errors:
            return JSONResponse({"errors": errors}, status_code=400)

        config.deployers[name] = NamedResourceConfig(name=name, type=resource_type, settings=dict(settings))
        save_config(config, include_resources=True)
        _reload_runtime(request.app)
        return JSONResponse({"ok": True, "name": name})

    @app.post("/api/deployers/{name}/update")
    async def api_update_deployer(request: Request, name: str):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        body = await request.json()
        csrf_token = body.get("csrf_token", "")
        validate_csrf(request, csrf_token)

        config = request.app.state.runtime.config
        existing = config.deployers.get(name)
        if existing is None:
            return JSONResponse({"errors": [f"部署目标 '{name}' 不存在。"]}, status_code=404)

        resource_type = str(body.get("type", "")).strip()
        settings = body.get("settings", {})

        errors = _validate_resource_fields(name, resource_type, settings, DEPLOYER_TYPES, is_new=False)
        if errors:
            return JSONResponse({"errors": errors}, status_code=400)

        # 保留 *** 未修改的敏感字段原值
        merged = {}
        for key, val in settings.items():
            if val == "******" and key in existing.settings:
                merged[key] = existing.settings[key]
            else:
                merged[key] = val

        existing.type = resource_type
        existing.settings = merged
        save_config(config, include_resources=True)
        _reload_runtime(request.app)
        return JSONResponse({"ok": True, "name": name})

    @app.post("/api/deployers/{name}/delete")
    async def api_delete_deployer(request: Request, name: str):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        body = await request.json()
        csrf_token = body.get("csrf_token", "")
        validate_csrf(request, csrf_token)

        config = request.app.state.runtime.config
        if name not in config.deployers:
            return JSONResponse({"errors": [f"部署目标 '{name}' 不存在。"]}, status_code=404)

        # 检查证书引用
        refs = [c.domain for c in config.certificates if name in c.deploy_to]
        if refs:
            return JSONResponse(
                {"errors": [f"以下证书正在使用此部署目标：{', '.join(refs)}，请先移除引用。"]},
                status_code=400,
            )

        del config.deployers[name]
        save_config(config, include_resources=True)
        _reload_runtime(request.app)
        return JSONResponse({"ok": True})

    @app.get("/api/deployers/{name}")
    async def api_get_deployer(request: Request, name: str):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        config = request.app.state.runtime.config
        res = config.deployers.get(name)
        if res is None:
            return JSONResponse({"errors": [f"部署目标 '{name}' 不存在。"]}, status_code=404)
        settings = dict(res.settings)
        for key in settings:
            if key in SENSITIVE_FIELDS:
                settings[key] = "******"
        return JSONResponse({"name": name, "type": res.type, "settings": settings})

    # ── DNS 提供商 API ──

    @app.get("/api/dns-providers")
    async def api_list_dns_providers(request: Request):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        config = request.app.state.runtime.config
        items = []
        for name, res in config.dns_providers.items():
            settings = dict(res.settings)
            for key in settings:
                if key in SENSITIVE_FIELDS:
                    settings[key] = "******"
            items.append({"name": name, "type": res.type, "settings": settings})
        return JSONResponse({"items": items, "types": DNS_PROVIDER_TYPE_LABELS})

    @app.post("/api/dns-providers")
    async def api_create_dns_provider(request: Request):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        body = await request.json()
        csrf_token = body.get("csrf_token", "")
        validate_csrf(request, csrf_token)

        name = str(body.get("name", "")).strip()
        resource_type = str(body.get("type", "")).strip()
        settings = body.get("settings", {})

        errors = _validate_resource_fields(name, resource_type, settings, DNS_PROVIDER_TYPES, is_new=True)
        config = request.app.state.runtime.config
        if name in config.dns_providers:
            errors.append(f"DNS 提供商 '{name}' 已存在。")
        if errors:
            return JSONResponse({"errors": errors}, status_code=400)

        config.dns_providers[name] = NamedResourceConfig(name=name, type=resource_type, settings=dict(settings))
        save_config(config, include_resources=True)
        _reload_runtime(request.app)
        return JSONResponse({"ok": True, "name": name})

    @app.post("/api/dns-providers/{name}/update")
    async def api_update_dns_provider(request: Request, name: str):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        body = await request.json()
        csrf_token = body.get("csrf_token", "")
        validate_csrf(request, csrf_token)

        config = request.app.state.runtime.config
        existing = config.dns_providers.get(name)
        if existing is None:
            return JSONResponse({"errors": [f"DNS 提供商 '{name}' 不存在。"]}, status_code=404)

        resource_type = str(body.get("type", "")).strip()
        settings = body.get("settings", {})

        errors = _validate_resource_fields(name, resource_type, settings, DNS_PROVIDER_TYPES, is_new=False)
        if errors:
            return JSONResponse({"errors": errors}, status_code=400)

        merged = {}
        for key, val in settings.items():
            if val == "******" and key in existing.settings:
                merged[key] = existing.settings[key]
            else:
                merged[key] = val

        existing.type = resource_type
        existing.settings = merged
        save_config(config, include_resources=True)
        _reload_runtime(request.app)
        return JSONResponse({"ok": True, "name": name})

    @app.post("/api/dns-providers/{name}/delete")
    async def api_delete_dns_provider(request: Request, name: str):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        body = await request.json()
        csrf_token = body.get("csrf_token", "")
        validate_csrf(request, csrf_token)

        config = request.app.state.runtime.config
        if name not in config.dns_providers:
            return JSONResponse({"errors": [f"DNS 提供商 '{name}' 不存在。"]}, status_code=404)

        # 检查证书引用
        refs = [c.domain for c in config.certificates if c.dns_provider == name]
        if refs:
            return JSONResponse(
                {"errors": [f"以下证书正在使用此 DNS 提供商：{', '.join(refs)}，请先移除引用。"]},
                status_code=400,
            )

        del config.dns_providers[name]
        save_config(config, include_resources=True)
        _reload_runtime(request.app)
        return JSONResponse({"ok": True})

    @app.get("/api/dns-providers/{name}")
    async def api_get_dns_provider(request: Request, name: str):
        if not request.session.get("authenticated"):
            return JSONResponse({"error": "未授权"}, status_code=401)
        config = request.app.state.runtime.config
        res = config.dns_providers.get(name)
        if res is None:
            return JSONResponse({"errors": [f"DNS 提供商 '{name}' 不存在。"]}, status_code=404)
        settings = dict(res.settings)
        for key in settings:
            if key in SENSITIVE_FIELDS:
                settings[key] = "******"
        return JSONResponse({"name": name, "type": res.type, "settings": settings})


def _validate_resource_fields(
    name: str,
    resource_type: str,
    settings: dict,
    type_defs: dict,
    *,
    is_new: bool = True,
) -> list[str]:
    """校验资源名称和字段。"""
    from certkeeper.web.resource_fields import FieldDef

    errors: list[str] = []
    if not name:
        errors.append("名称不能为空。")
    if not resource_type:
        errors.append("请选择类型。")
    elif resource_type not in type_defs:
        errors.append(f"不支持的类型: {resource_type}")
    else:
        fields: list[FieldDef] = type_defs[resource_type]
        for f in fields:
            val = settings.get(f.name, "")
            if f.required and not str(val).strip():
                errors.append(f"{f.label} 不能为空。")
    return errors


def _resolve_path(config_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return config_path.parent / candidate
