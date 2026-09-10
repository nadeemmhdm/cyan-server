from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from security.auth import authenticate, create_token
from security.dependencies import require_admin
from security.rate_limit import (
    check_rate_limit, check_lockout, record_failed_login,
    record_successful_login, RateLimitExceeded, AccountLocked,
)
from core.database import AuditLog, get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def _audit(event: str, username: str | None, source_ip: str | None, detail: str = ""):
    session = get_session()
    try:
        session.add(AuditLog(event=event, username=username, source_ip=source_ip, detail=detail))
        session.commit()
    finally:
        session.close()


@router.post("/login")
def login(req: LoginRequest, request: Request):
    source_ip = request.client.host if request.client else "unknown"

    try:
        check_rate_limit(source_ip)
    except RateLimitExceeded:
        _audit("login_rate_limited", req.username, source_ip)
        raise HTTPException(429, "Too many login attempts. Try again shortly.")

    try:
        check_lockout(req.username)
    except AccountLocked as e:
        _audit("login_locked", req.username, source_ip, str(e))
        raise HTTPException(423, f"Account temporarily locked after repeated failed attempts. "
                                  f"Retry in {e.retry_after_seconds:.0f}s.")

    user = authenticate(req.username, req.password)
    if not user:
        record_failed_login(req.username)
        _audit("login_failed", req.username, source_ip)
        raise HTTPException(401, "Invalid username or password")

    record_successful_login(req.username)
    _audit("login_success", req.username, source_ip)
    token = create_token(user)
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@router.get("/audit-log")
def audit_log(limit: int = 50, _=Depends(require_admin)):
    """Admin-only audit trail of login attempts."""
    session = get_session()
    try:
        rows = session.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
        return [{
            "event": r.event, "username": r.username, "source_ip": r.source_ip,
            "detail": r.detail, "created_at": r.created_at.isoformat(),
        } for r in rows]
    finally:
        session.close()
