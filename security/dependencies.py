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
