"""Web UI 认证与密码工具。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from fastapi import HTTPException, Request, status


def hash_password(password: str, *, salt: str | None = None, iterations: int = 600_000) -> str:
    """生成 PBKDF2-SHA256 密码哈希。"""

    resolved_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        resolved_salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${resolved_salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """校验明文密码与已保存哈希是否匹配。"""

    try:
        algorithm, iterations_text, salt, digest = stored_hash.split("$", maxsplit=3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    recalculated = hash_password(password, salt=salt, iterations=int(iterations_text))
    return hmac.compare_digest(recalculated, stored_hash)


def ensure_csrf_token(session: dict[str, Any]) -> str:
    """确保会话中存在 CSRF token。"""

    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(24)
        session["csrf_token"] = token
    return str(token)


def validate_csrf(request: Request, submitted_token: str | None) -> None:
    """校验提交的 CSRF token。"""

    session_token = request.session.get("csrf_token")
    if not session_token or not submitted_token or not hmac.compare_digest(str(session_token), submitted_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无效的 CSRF token。")


def require_login(request: Request) -> None:
    """要求当前请求已经登录。"""

    if not request.session.get("authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录。")
