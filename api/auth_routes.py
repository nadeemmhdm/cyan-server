# Cyan Server — https://github.com/nadeemmhdm/cyan-server
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from security.auth import authenticate, create_token
from security.dependencies import require_admin
from security.rate_limit import (
    check_rate_limit, check_lockout, record_failed_login,
    record_successful_login, RateLimitExceeded, AccountLocked,
)
from core.database import AuditLog, User, get_session

from security.totp import generate_secret, verify_totp, get_otpauth_uri

router = APIRouter(prefix="/api/auth", tags=["auth"])

_pending_2fa: dict[str, str] = {}


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class Enable2FARequest(BaseModel):
    code: str


class Disable2FARequest(BaseModel):
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

    # If 2FA is enabled on this account, challenge for TOTP code
    if getattr(user, "totp_enabled", False):
        if not req.totp_code:
            return {
                "require_2fa": True,
                "message": "Two-factor authentication code required",
            }
        if not verify_totp(user.totp_secret or "", req.totp_code):
            record_failed_login(req.username)
            _audit("login_failed_2fa", req.username, source_ip)
            raise HTTPException(401, "Invalid two-factor authentication code")

    record_successful_login(req.username)
    _audit("login_success", req.username, source_ip)
    token = create_token(user)
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@router.get("/me")
def get_current_user_profile(payload: dict = Depends(require_admin)):
    """Return profile details for the currently logged in administrator."""
    session = get_session()
    try:
        user = session.query(User).filter_by(username=payload.get("sub")).first()
        if not user:
            raise HTTPException(404, "User profile not found")
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "totp_enabled": bool(user.totp_enabled),
        }
    finally:
        session.close()


@router.get("/2fa/status")
def get_2fa_status(payload: dict = Depends(require_admin)):
    session = get_session()
    try:
        user = session.query(User).filter_by(username=payload.get("sub")).first()
        if not user:
            raise HTTPException(404, "User not found")
        return {"enabled": bool(user.totp_enabled)}
    finally:
        session.close()


@router.post("/2fa/setup")
def setup_2fa(payload: dict = Depends(require_admin)):
    username = payload.get("sub")
    secret = generate_secret()
    _pending_2fa[username] = secret
    uri = get_otpauth_uri(secret, username)
    return {"secret": secret, "otpauth_url": uri}


@router.post("/2fa/enable")
def enable_2fa(req: Enable2FARequest, request: Request, payload: dict = Depends(require_admin)):
    username = payload.get("sub")
    source_ip = request.client.host if request.client else "unknown"
    secret = _pending_2fa.get(username)
    if not secret:
        raise HTTPException(400, "2FA setup has not been initiated. Please click Enable 2FA again.")
    if not verify_totp(secret, req.code):
        _audit("2fa_enable_failed", username, source_ip, "invalid code")
        raise HTTPException(400, "Invalid 6-digit verification code. Check your authenticator app clock.")

    session = get_session()
    try:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            raise HTTPException(404, "User not found")
        user.totp_secret = secret
        user.totp_enabled = True
        session.commit()
        _pending_2fa.pop(username, None)
        _audit("2fa_enabled", username, source_ip)
        return {"success": True, "message": "Two-factor authentication enabled successfully"}
    finally:
        session.close()


@router.post("/2fa/disable")
def disable_2fa(req: Disable2FARequest, request: Request, payload: dict = Depends(require_admin)):
    from security.auth import verify_password
    username = payload.get("sub")
    source_ip = request.client.host if request.client else "unknown"
    session = get_session()
    try:
        user = session.query(User).filter_by(username=username).first()
        if not user or not verify_password(req.password, user.password_hash):
            _audit("2fa_disable_failed", username, source_ip, "incorrect password")
            raise HTTPException(400, "Current password is incorrect")

        user.totp_enabled = False
        user.totp_secret = None
        session.commit()
        _pending_2fa.pop(username, None)
        _audit("2fa_disabled", username, source_ip)
        return {"success": True, "message": "Two-factor authentication disabled"}
    finally:
        session.close()


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request, payload: dict = Depends(require_admin)):
    """Change the admin password. Verifies current password and updates hash."""
    from security.auth import verify_password, hash_password
    source_ip = request.client.host if request.client else "unknown"
    session = get_session()
    try:
        user = session.query(User).filter_by(username=payload.get("sub")).first()
        if not user or not verify_password(req.current_password, user.password_hash):
            _audit("password_change_failed", payload.get("sub"), source_ip, "incorrect current password")
            raise HTTPException(400, "Current password is incorrect")

        if len(req.new_password) < 6:
            raise HTTPException(400, "New password must be at least 6 characters long")

        user.password_hash = hash_password(req.new_password)
        session.commit()
        _audit("password_change_success", payload.get("sub"), source_ip)
        return {"success": True, "message": "Password changed successfully"}
    finally:
        session.close()


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

