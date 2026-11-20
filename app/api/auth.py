"""鉴权与 RBAC（G-06：/api/** 全量门禁，仅 /healthz 例外）。

令牌与角色只存 `~/.config/quant-pro/auth.json`（600），仓库不存真实令牌。
bootstrap 会生成一个 dev 令牌（全角色），便于开箱即用验收。
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException

from core.config import settings

ROLES = ("viewer", "researcher", "pm", "data", "risk")
AUTH_FILE = settings.SECRETS_DIR / "auth.json"


def ensure_dev_token() -> str:
    settings.SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    if AUTH_FILE.exists():
        blob = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        if blob.get("tokens"):
            return next(iter(blob["tokens"]))
    tok = "qp-" + secrets.token_urlsafe(24)
    blob = {"tokens": {tok: {"user": "dev", "roles": list(ROLES)}}}
    AUTH_FILE.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(AUTH_FILE, 0o600)
    return tok


def load_tokens() -> dict:
    if not AUTH_FILE.exists():
        ensure_dev_token()
    return json.loads(AUTH_FILE.read_text(encoding="utf-8")).get("tokens", {})


def principal(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "缺少 Bearer 令牌")
    tok = authorization[7:].strip()
    info = load_tokens().get(tok)
    if not info:
        raise HTTPException(401, "令牌无效或已过期")
    return {"user": info.get("user", "?"), "roles": info.get("roles", ["viewer"])}


def require(principal: dict, *roles: str) -> None:
    if not set(roles) & set(principal["roles"]):
        raise HTTPException(403, f"需要角色 {roles}，当前 {principal['roles']}")
