"""Web UI 应用入口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from certkeeper.runtime import build_runtime
from certkeeper.web.routes import register_routes


def create_app(config_path: str | Path) -> FastAPI:
    """根据配置文件创建 Web UI 应用。"""

    resolved_config_path = Path(config_path)
    runtime = build_runtime(resolved_config_path)
    app = FastAPI(title="CertKeeper Web UI")
    app.add_middleware(SessionMiddleware, secret_key=runtime.config.web_ui.session_secret or "dev-secret")
    app.state.runtime = runtime
    app.state.config_path = resolved_config_path
    register_routes(app)
    return app
