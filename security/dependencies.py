"""FastAPI dependency for JWT-authenticated, role-checked routes."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Header

from security.auth import decode_token


def require_auth(authorization: str | None = Header(default=None)) -> dict:
    """Raises 401 unless a valid 'Authorization: Bearer <token>' header is
    present. Returns the decoded JWT payload (sub=username, role=role)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    return payload


def require_admin(payload: dict = Depends(require_auth)) -> dict:
    if payload.get("role") != "admin":
        raise HTTPException(403, "Admin role required")
    return payload


from core.database import ApiKey, get_session
import datetime


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> ApiKey:
    """Authenticates external API requests via X-API-Key header or Bearer cyan_live_ token."""
    raw_key = x_api_key
    if not raw_key and authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[1].startswith("cyan_live_"):
            raw_key = parts[1].strip()
    if not raw_key:
        raise HTTPException(401, "Missing API Key (pass header 'X-API-Key' or 'Authorization: Bearer <key>')")

    session = get_session()
    try:
        key_obj = session.query(ApiKey).filter_by(key=raw_key).first()
        if not key_obj:
            raise HTTPException(401, "Invalid API Key")
        key_obj.last_used_at = datetime.datetime.utcnow()
        session.commit()
        return key_obj
    finally:
        session.close()


def require_auth_or_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    """Accepts either JWT session auth (from Dashboard/CLI) or an API key (external apps)."""
    if x_api_key or (authorization and "cyan_live_" in authorization):
        api_key = require_api_key(x_api_key=x_api_key, authorization=authorization)
        return {"sub": f"api_key:{api_key.name}", "role": "api_user", "api_key_id": api_key.id}
    return require_auth(authorization=authorization)
