# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Cyan Server - Auth Service
Email+password authentication as a feature other apps/sites can use,
scoped by project + API key. Real bcrypt hashing, real SMTP delivery of
verification links/OTPs (via a project's own SMTP credentials, collected
and verified only when this feature is actually used — nothing is sent
anywhere until a project configures SMTP), real progressive account
lockout backed by the database (not just in-memory), and a real password
policy. No mocked "email sent" responses — smtplib either delivers or
raises, and callers see which.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import re
import secrets
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from core.database import (
    AuthProject, AuthSMTPConfig, AuthEndUser, AuthVerification,
    AuthEmailTemplate, get_session, utcnow,
)
from security.auth import hash_password, verify_password

import jwt

JWT_ALGORITHM = "HS256"
SESSION_EXPIRY_HOURS = 12
MAX_LOCKOUT_HOURS = 24


class AuthSvcError(Exception):
    pass


class InvalidCredentials(AuthSvcError):
    pass


class AccountLocked(AuthSvcError):
    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Account temporarily locked. Try again in {retry_after_seconds / 60:.0f} min.")


# ---------------------------------------------------------------------------
# Secrets: a Fernet key (encrypts stored SMTP app passwords) and a JWT
# signing secret, both separate from the admin-dashboard's own secrets so a
# leaked end-user session token can never be replayed against the admin
# dashboard or vice versa.
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    d = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_fernet() -> Fernet:
    path = _data_dir() / ".authsvc_fernet_key"
    if path.exists():
        key = path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        path.write_bytes(key)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return Fernet(key)


def _authsvc_jwt_secret() -> str:
    path = _data_dir() / ".authsvc_jwt_secret"
    if path.exists():
        return path.read_text().strip()
    secret = secrets.token_hex(32)
    path.write_text(secret)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise AuthSvcError("Stored SMTP credential could not be decrypted — reconfigure SMTP for this project.")


# ---------------------------------------------------------------------------
# API keys / project IDs
# ---------------------------------------------------------------------------

def _generate_api_key() -> str:
    return f"ck_live_{secrets.token_urlsafe(32)}"


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_project_id() -> str:
    return f"proj_{secrets.token_hex(8)}"


def _generate_user_public_id() -> str:
    """14 hex chars — within the requested 12-15 length range, and short
    enough to read/copy comfortably while still effectively collision-free."""
    return secrets.token_hex(7)


# ---------------------------------------------------------------------------
# Password policy — "secure password only"
# ---------------------------------------------------------------------------

_COMMON_WEAK_PASSWORDS = {
    "password", "password1", "12345678", "123456789", "qwerty123",
    "letmein1", "welcome1", "admin123", "iloveyou", "changeme",
}


def validate_password_strength(password: str, min_length: int, email: str | None = None) -> None:
    if len(password) < min_length:
        raise AuthSvcError(f"Password must be at least {min_length} characters long")
    if len(password) > 128:
        raise AuthSvcError("Password must be at most 128 characters long")
    if not re.search(r"[a-z]", password):
        raise AuthSvcError("Password must include at least one lowercase letter")
    if not re.search(r"[A-Z]", password):
        raise AuthSvcError("Password must include at least one uppercase letter")
    if not re.search(r"\d", password):
        raise AuthSvcError("Password must include at least one digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise AuthSvcError("Password must include at least one special character")
    if password.lower() in _COMMON_WEAK_PASSWORDS:
        raise AuthSvcError("Password is too common — choose something less guessable")
    if email:
        local_part = email.split("@")[0].lower()
        if local_part and local_part in password.lower():
            raise AuthSvcError("Password must not contain your email address")


# ---------------------------------------------------------------------------
# Default email templates — {{otp}}, {{link}}, {{email}}, {{project_name}}
# ---------------------------------------------------------------------------

def _default_templates() -> dict[str, dict[str, str]]:
    return {
        "email_verify": {
            "subject": "Verify your email for {{project_name}}",
            "body_html": (
                "<p>Hi,</p>"
                "<p>Confirm your email for <b>{{project_name}}</b> using either option below:</p>"
                "<p><a href=\"{{link}}\">Click here to verify your email</a></p>"
                "<p>Or enter this one-time code: <b style=\"font-size:20px;letter-spacing:4px\">{{otp}}</b></p>"
                "<p>This code/link expires in {{ttl_minutes}} minutes and can only be used once. "
                "If you didn't request this, ignore it.</p>"
            ),
        },
        "password_reset": {
            "subject": "Reset your password for {{project_name}}",
            "body_html": (
                "<p>Hi,</p>"
                "<p>Reset your password for <b>{{project_name}}</b> using either option below:</p>"
                "<p><a href=\"{{link}}\">Click here to reset your password</a></p>"
                "<p>Or enter this one-time code: <b style=\"font-size:20px;letter-spacing:4px\">{{otp}}</b></p>"
                "<p>This code/link expires in {{ttl_minutes}} minutes and can only be used once. "
                "If you didn't request this, your password is still safe — just ignore this email.</p>"
            ),
        },
        "email_change": {
            "subject": "Confirm your new email for {{project_name}}",
            "body_html": (
                "<p>Hi,</p>"
                "<p>Confirm this address as your new login email for <b>{{project_name}}</b>:</p>"
                "<p><a href=\"{{link}}\">Click here to confirm your new email</a></p>"
                "<p>Or enter this one-time code in the app: <b style=\"font-size:20px;letter-spacing:4px\">{{otp}}</b></p>"
                "<p>This code/link expires in {{ttl_minutes}} minutes and can only be used once. "
                "If you didn't request this change, your email is unchanged — just ignore this message.</p>"
            ),
        },
        "mfa_login": {
            "subject": "Your {{project_name}} sign-in code",
            "body_html": (
                "<p>Hi,</p>"
                "<p>Someone is signing in to your <b>{{project_name}}</b> account. "
                "Enter this code to finish signing in:</p>"
                "<p><b style=\"font-size:20px;letter-spacing:4px\">{{otp}}</b></p>"
                "<p>This code expires in {{ttl_minutes}} minutes and can only be used once. "
                "If this wasn't you, change your password immediately.</p>"
            ),
        },
    }


def _render(template: str, **kwargs) -> str:
    out = template
    for k, v in kwargs.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def create_project(name: str, description: str = "") -> dict:
    if not name or not name.strip():
        raise AuthSvcError("Project name is required")

    raw_key = _generate_api_key()
    session = get_session()
    try:
        project = AuthProject(
            project_id=_generate_project_id(),
            name=name.strip(),
            description=description or "",
            api_key_hash=_hash_api_key(raw_key),
            api_key_prefix=raw_key[:16] + "…",
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        for ttype, tpl in _default_templates().items():
            session.add(AuthEmailTemplate(
                project_id=project.id, template_type=ttype,
                subject=tpl["subject"], body_html=tpl["body_html"],
            ))
        session.commit()

        return {
            "project_id": project.project_id,
            "name": project.name,
            "description": project.description,
            "api_key": raw_key,   # shown exactly once — caller must store it now
            "api_key_prefix": project.api_key_prefix,
            "warning": "Store this API key now — it will not be shown again. "
                       "Only its prefix is retrievable later.",
        }
    finally:
        session.close()


def list_projects() -> list[dict]:
    session = get_session()
    try:
        return [{
            "project_id": p.project_id, "name": p.name, "description": p.description,
            "api_key_prefix": p.api_key_prefix,
            "require_email_verification": p.require_email_verification,
            "mfa_enabled": p.mfa_enabled,
            "password_min_length": p.password_min_length,
            "max_login_attempts": p.max_login_attempts,
            "lockout_minutes": p.lockout_minutes,
            "smtp_configured": session.query(AuthSMTPConfig).filter_by(project_id=p.id).first() is not None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        } for p in session.query(AuthProject).all()]
    finally:
        session.close()


def _get_project_by_project_id(session, project_id: str) -> AuthProject:
    project = session.query(AuthProject).filter_by(project_id=project_id).first()
    if not project:
        raise AuthSvcError(f"Project '{project_id}' not found")
    return project


def _get_project_by_api_key(session, raw_key: str) -> AuthProject:
    project = session.query(AuthProject).filter_by(api_key_hash=_hash_api_key(raw_key)).first()
    if not project:
        # Deliberately generic — never confirm/deny whether a key format is close.
        raise AuthSvcError("Invalid API key")
    return project


def _get_user_in_project(session, project: AuthProject, *, email: str | None = None,
                          user_id: int | None = None) -> AuthEndUser | None:
    """The one place any end-user row is ever fetched by email or id — every
    call site MUST go through here rather than querying AuthEndUser
    directly, so a project_id filter can never be forgotten in a future
    change. This is the application-layer row-level security boundary:
    a project's API key, session token, or admin session can only ever
    resolve rows that also match project.id, however the row was looked
    up. (The one exception is token-based verification lookups, where the
    single-use token itself — not project_id — is the scoping credential;
    those still resolve the owning project from the row afterward rather
    than accepting one as input, so a token from project A can never be
    replayed as if it belonged to project B.)"""
    q = session.query(AuthEndUser).filter_by(project_id=project.id)
    if email is not None:
        q = q.filter_by(email=email)
    if user_id is not None:
        q = q.filter_by(id=user_id)
    return q.first()


def update_project_policy(project_id: str, require_email_verification: bool | None = None,
                           password_min_length: int | None = None,
                           max_login_attempts: int | None = None,
                           lockout_minutes: int | None = None,
                           mfa_enabled: bool | None = None) -> dict:
    session = get_session()
    try:
        project = _get_project_by_project_id(session, project_id)
        if require_email_verification is not None:
            project.require_email_verification = require_email_verification
        if mfa_enabled is not None:
            if mfa_enabled and not session.query(AuthSMTPConfig).filter_by(project_id=project.id).first():
                raise AuthSvcError("Configure SMTP before enabling MFA — the OTP has to be emailed somewhere")
            project.mfa_enabled = mfa_enabled
        if password_min_length is not None:
            if password_min_length < 8:
                raise AuthSvcError("password_min_length must be at least 8")
            project.password_min_length = password_min_length
        if max_login_attempts is not None:
            if max_login_attempts < 3:
                raise AuthSvcError("max_login_attempts must be at least 3")
            project.max_login_attempts = max_login_attempts
        if lockout_minutes is not None:
            if lockout_minutes < 1:
                raise AuthSvcError("lockout_minutes must be at least 1")
            project.lockout_minutes = lockout_minutes
        session.commit()
        return {"project_id": project.project_id, "updated": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# SMTP configuration — collected only when a project actually needs it, and
# verified with a real connection before it's trusted.
# ---------------------------------------------------------------------------

def configure_smtp(project_id: str, host: str, port: int, email: str, app_password: str,
                    use_tls: bool = True, from_name: str = "Cyan Server", verify: bool = True) -> dict:
    if not host or not email or not app_password:
        raise AuthSvcError("host, email, and app_password are all required")
    if not (1 <= port <= 65535):
        raise AuthSvcError("port must be between 1 and 65535")

    if verify:
        _verify_smtp_credentials(host, port, email, app_password, use_tls)

    session = get_session()
    try:
        project = _get_project_by_project_id(session, project_id)
        existing = session.query(AuthSMTPConfig).filter_by(project_id=project.id).first()
        encrypted = encrypt_secret(app_password)
        if existing:
            existing.host, existing.port, existing.email = host, port, email
            existing.app_password_encrypted = encrypted
            existing.use_tls, existing.from_name = use_tls, from_name
        else:
            session.add(AuthSMTPConfig(
                project_id=project.id, host=host, port=port, email=email,
                app_password_encrypted=encrypted, use_tls=use_tls, from_name=from_name,
            ))
        session.commit()
        return {"project_id": project_id, "smtp_configured": True, "verified": verify}
    finally:
        session.close()


def _verify_smtp_credentials(host: str, port: int, email: str, app_password: str, use_tls: bool) -> None:
    """A real connection + login attempt, not a format check — this is the
    'check user SMTP details' step the feature is gated behind."""
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                server.starttls(context=ssl.create_default_context())
        try:
            server.login(email, app_password)
        finally:
            server.quit()
    except smtplib.SMTPAuthenticationError as e:
        raise AuthSvcError(f"SMTP authentication failed: {e.smtp_error.decode(errors='ignore') if isinstance(e.smtp_error, bytes) else e.smtp_error}")
    except (smtplib.SMTPException, OSError, TimeoutError) as e:
        raise AuthSvcError(f"Could not connect to SMTP server: {e}")


def _get_smtp_config(session, project: AuthProject) -> AuthSMTPConfig:
    cfg = session.query(AuthSMTPConfig).filter_by(project_id=project.id).first()
    if not cfg:
        raise AuthSvcError(
            "This project has no SMTP configured yet — set it up first "
            "(cyan auth smtp <project_id> or POST /api/authsvc/projects/{project_id}/smtp) "
            "before registering users."
        )
    return cfg


def _send_email(cfg: AuthSMTPConfig, to_email: str, subject: str, html_body: str) -> None:
    password = decrypt_secret(cfg.app_password_encrypted)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg.from_name} <{cfg.email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    if cfg.port == 465:
        server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
        if cfg.use_tls:
            server.starttls(context=ssl.create_default_context())
    try:
        server.login(cfg.email, password)
        server.sendmail(cfg.email, [to_email], msg.as_string())
    finally:
        server.quit()


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------

def get_templates(project_id: str) -> list[dict]:
    session = get_session()
    try:
        project = _get_project_by_project_id(session, project_id)
        rows = session.query(AuthEmailTemplate).filter_by(project_id=project.id).all()
        return [{"template_type": r.template_type, "subject": r.subject, "body_html": r.body_html}
                for r in rows]
    finally:
        session.close()


def update_template(project_id: str, template_type: str, subject: str, body_html: str) -> dict:
    if template_type not in ("email_verify", "password_reset", "email_change", "mfa_login"):
        raise AuthSvcError("template_type must be one of: email_verify, password_reset, email_change, mfa_login")
    session = get_session()
    try:
        project = _get_project_by_project_id(session, project_id)
        row = session.query(AuthEmailTemplate).filter_by(
            project_id=project.id, template_type=template_type).first()
        if not row:
            row = AuthEmailTemplate(project_id=project.id, template_type=template_type,
                                     subject=subject, body_html=body_html)
            session.add(row)
        else:
            row.subject, row.body_html = subject, body_html
        session.commit()
        return {"project_id": project_id, "template_type": template_type, "updated": True}
    finally:
        session.close()


def _get_template(session, project: AuthProject, template_type: str) -> AuthEmailTemplate:
    row = session.query(AuthEmailTemplate).filter_by(
        project_id=project.id, template_type=template_type).first()
    if row:
        return row
    default = _default_templates()[template_type]
    return AuthEmailTemplate(project_id=project.id, template_type=template_type, **{
        "subject": default["subject"], "body_html": default["body_html"],
    })


# ---------------------------------------------------------------------------
# Verification (link + OTP), issued together so either path works
# ---------------------------------------------------------------------------

def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _issue_verification(session, project: AuthProject, user: AuthEndUser, purpose: str,
                         new_email: str | None = None) -> tuple[AuthVerification, str]:
    """Returns (row, raw_token). Only the HASH of the token is ever
    persisted — the raw value exists only in memory here and in the
    email sent to the user, so a database leak alone can never yield a
    working verification link."""
    # Invalidate any outstanding, unconsumed verification of the same purpose
    # for this user first, so an old link/OTP can't be replayed alongside a new one.
    session.query(AuthVerification).filter_by(
        user_id=user.id, purpose=purpose, consumed=False
    ).update({"consumed": True})

    raw_token = secrets.token_urlsafe(32)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    v = AuthVerification(
        user_id=user.id, purpose=purpose, token=_hash_token(raw_token), otp_code=otp,
        new_email=new_email,
        expires_at=utcnow() + datetime.timedelta(minutes=project.otp_ttl_minutes),
    )
    session.add(v)
    session.commit()
    session.refresh(v)
    return v, raw_token


def _find_verification_by_token(session, raw_token: str, purpose: str) -> AuthVerification | None:
    return session.query(AuthVerification).filter_by(
        token=_hash_token(raw_token), purpose=purpose, consumed=False).first()


def _deliver_verification(session, project: AuthProject, user: AuthEndUser,
                           raw_token: str, otp_code: str, purpose: str,
                           base_link_url: str | None, to_email: str | None = None) -> None:
    cfg = _get_smtp_config(session, project)
    template = _get_template(session, project, purpose)
    page = {"email_verify": "verify-email", "password_reset": "reset-password",
            "email_change": "confirm-email-change"}.get(purpose)
    if page:
        link = f"{(base_link_url or '').rstrip('/')}/api/authsvc/{page}?token={raw_token}" if base_link_url \
            else f"cyan://authsvc/{page}?token={raw_token}"
    else:
        link = ""   # mfa_login has no clickable link — code-only, entered back into the app
    subject = _render(template.subject, project_name=project.name)
    body = _render(template.body_html, project_name=project.name, otp=otp_code,
                    link=link, email=user.email, ttl_minutes=project.otp_ttl_minutes)
    _send_email(cfg, to_email or user.email, subject, body)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_user(api_key: str, email: str, password: str, base_link_url: str | None = None) -> dict:
    email = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise AuthSvcError("Invalid email address")

    session = get_session()
    try:
        project = _get_project_by_api_key(session, api_key)
        validate_password_strength(password, project.password_min_length, email=email)

        existing = _get_user_in_project(session, project, email=email)
        if existing:
            raise AuthSvcError("An account with this email already exists")

        public_id = _generate_user_public_id()
        while session.query(AuthEndUser).filter_by(public_id=public_id).first():
            public_id = _generate_user_public_id()  # practically never happens; belt and suspenders

        user = AuthEndUser(public_id=public_id, project_id=project.id, email=email,
                            password_hash=hash_password(password),
                            email_verified=not project.require_email_verification)
        session.add(user)
        session.commit()
        session.refresh(user)

        email_sent = False
        if project.require_email_verification:
            verification, raw_token = _issue_verification(session, project, user, "email_verify")
            _deliver_verification(session, project, user, raw_token, verification.otp_code,
                                   "email_verify", base_link_url)
            email_sent = True

        return {
            "email": user.email,
            "user_id": user.public_id,
            "email_verification_required": project.require_email_verification,
            "email_sent": email_sent,
            "status": "pending_verification" if project.require_email_verification else "active",
        }
    finally:
        session.close()


def resend_verification(api_key: str, email: str, base_link_url: str | None = None) -> dict:
    email = (email or "").strip().lower()
    session = get_session()
    try:
        project = _get_project_by_api_key(session, api_key)
        user = _get_user_in_project(session, project, email=email)
        if not user:
            # Same response either way — don't leak whether an email is registered.
            return {"email_sent": True}
        if user.email_verified:
            return {"email_sent": False, "reason": "already_verified"}

        latest = session.query(AuthVerification).filter_by(
            user_id=user.id, purpose="email_verify", consumed=False
        ).order_by(AuthVerification.created_at.desc()).first()
        if latest and (utcnow() - latest.created_at).total_seconds() < 60:
            raise AuthSvcError("Please wait at least 60 seconds between resend requests")

        verification, raw_token = _issue_verification(session, project, user, "email_verify")
        _deliver_verification(session, project, user, raw_token, verification.otp_code,
                               "email_verify", base_link_url)
        return {"email_sent": True}
    finally:
        session.close()


def verify_email_token(token: str) -> dict:
    """Single-use: the row is marked consumed in the same transaction that
    checks it, so a link opened twice (browser prefetch, email scanners,
    a second click) only succeeds once."""
    session = get_session()
    try:
        v = _find_verification_by_token(session, token, "email_verify")
        if not v or v.expires_at < utcnow():
            raise AuthSvcError("Verification link is invalid, already used, or has expired")
        user = session.query(AuthEndUser).filter_by(id=v.user_id).first()
        v.consumed = True
        user.email_verified = True
        user.verification_method = "link"
        session.commit()
        return {"email": user.email, "verified": True}
    finally:
        session.close()




# ---------------------------------------------------------------------------
# Login — real, database-backed progressive lockout (survives restarts,
# unlike the admin dashboard's in-memory limiter, since these are external
# end-user accounts that could be targeted over a long period). Optional
# email-OTP second factor: on a project with mfa_enabled, a correct
# password alone doesn't issue a session — it issues a short-lived
# pre-auth token and emails a one-time code that must be exchanged for
# the real session via mfa_verify().
# ---------------------------------------------------------------------------

PREAUTH_EXPIRY_MINUTES = 5


def _issue_session_token(project: AuthProject, user: AuthEndUser) -> str:
    payload = {
        "aud": "authsvc",
        "project_id": project.project_id,
        "sub": str(user.id),
        "email": user.email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=SESSION_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _authsvc_jwt_secret(), algorithm=JWT_ALGORITHM)


def _issue_preauth_token(project: AuthProject, user: AuthEndUser) -> str:
    payload = {
        "aud": "authsvc_preauth",
        "project_id": project.project_id,
        "sub": str(user.id),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=PREAUTH_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, _authsvc_jwt_secret(), algorithm=JWT_ALGORITHM)


def verify_session_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _authsvc_jwt_secret(), algorithms=[JWT_ALGORITHM], audience="authsvc")
    except jwt.PyJWTError:
        raise AuthSvcError("Invalid or expired session token")
    return payload


def _verify_preauth_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _authsvc_jwt_secret(), algorithms=[JWT_ALGORITHM], audience="authsvc_preauth")
    except jwt.PyJWTError:
        raise AuthSvcError("Sign-in expired — start over")
    return payload


def login(api_key: str, email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    session = get_session()
    try:
        project = _get_project_by_api_key(session, api_key)
        user = _get_user_in_project(session, project, email=email)

        # Constant-shape response whether or not the account exists, to avoid
        # user enumeration — but still needs a bcrypt-shaped comparison so
        # timing doesn't leak it either; verify_password against a fixed
        # dummy hash costs the same as a real one.
        dummy_hash = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO0j9k9k3v5b7l3c7z0r3g6p4h2s1n8Ke"
        if not user:
            verify_password(password, dummy_hash)
            raise InvalidCredentials("Invalid email or password")

        if user.disabled:
            raise AuthSvcError("This account has been disabled")

        if user.locked_until and user.locked_until > utcnow():
            raise AccountLocked((user.locked_until - utcnow()).total_seconds())
        if user.locked_until and user.locked_until <= utcnow():
            user.locked_until = None
            user.failed_attempts = 0

        if project.require_email_verification and not user.email_verified:
            raise AuthSvcError("Email not verified — check your inbox or request a new code")

        if not verify_password(password, user.password_hash):
            user.failed_attempts += 1
            if user.failed_attempts >= project.max_login_attempts:
                user.lockout_count += 1
                # Progressive backoff: lockout_minutes * 2^(lockout_count-1), capped.
                minutes = min(project.lockout_minutes * (2 ** (user.lockout_count - 1)),
                              MAX_LOCKOUT_HOURS * 60)
                user.locked_until = utcnow() + datetime.timedelta(minutes=minutes)
                user.failed_attempts = 0
                session.commit()
                raise AccountLocked(minutes * 60)
            session.commit()
            raise InvalidCredentials("Invalid email or password")

        user.failed_attempts = 0
        user.lockout_count = 0
        session.commit()

        if project.mfa_enabled:
            verification, raw_otp_unused = _issue_verification(session, project, user, "mfa_login")
            _deliver_verification(session, project, user, "", verification.otp_code, "mfa_login", None)
            preauth = _issue_preauth_token(project, user)
            return {"mfa_required": True, "preauth_token": preauth,
                    "expires_in_minutes": PREAUTH_EXPIRY_MINUTES}

        token = _issue_session_token(project, user)
        return {"email": user.email, "session_token": token, "expires_in_hours": SESSION_EXPIRY_HOURS}
    finally:
        session.close()


def mfa_verify(preauth_token: str, otp: str) -> dict:
    payload = _verify_preauth_token(preauth_token)
    session = get_session()
    try:
        project = _get_project_by_project_id(session, payload["project_id"])
        user = _get_user_in_project(session, project, user_id=int(payload["sub"]))
        if not user:
            raise AuthSvcError("Invalid or expired code")
        v = session.query(AuthVerification).filter_by(
            user_id=user.id, purpose="mfa_login", consumed=False
        ).order_by(AuthVerification.created_at.desc()).first()
        if not v or v.expires_at < utcnow() or not secrets.compare_digest(v.otp_code, (otp or "").strip()):
            raise AuthSvcError("Invalid or expired code")
        v.consumed = True
        session.commit()

        token = _issue_session_token(project, user)
        return {"email": user.email, "session_token": token, "expires_in_hours": SESSION_EXPIRY_HOURS}
    finally:
        session.close()


def verify_email_otp(api_key: str, email: str, otp: str) -> dict:
    email = (email or "").strip().lower()
    session = get_session()
    try:
        project = _get_project_by_api_key(session, api_key)
        user = _get_user_in_project(session, project, email=email)
        if not user:
            raise AuthSvcError("Invalid code")
        v = session.query(AuthVerification).filter_by(
            user_id=user.id, purpose="email_verify", consumed=False
        ).order_by(AuthVerification.created_at.desc()).first()
        if not v or v.expires_at < utcnow() or not secrets.compare_digest(v.otp_code, (otp or "").strip()):
            raise AuthSvcError("Invalid or expired code")
        v.consumed = True
        user.email_verified = True
        user.verification_method = "otp"
        session.commit()
        return {"email": user.email, "verified": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def forgot_password(api_key: str, email: str, base_link_url: str | None = None) -> dict:
    email = (email or "").strip().lower()
    session = get_session()
    try:
        project = _get_project_by_api_key(session, api_key)
        user = _get_user_in_project(session, project, email=email)
        if not user:
            return {"email_sent": True}  # don't leak account existence
        verification, raw_token = _issue_verification(session, project, user, "password_reset")
        _deliver_verification(session, project, user, raw_token, verification.otp_code,
                               "password_reset", base_link_url)
        return {"email_sent": True}
    finally:
        session.close()


def reset_password(api_key: str, email: str, otp: str, new_password: str) -> dict:
    """The OTP path — pairs with api_key+email like the rest of the
    API-key-scoped flows. For the emailed LINK, use reset_password_by_token
    instead: the token alone is proof enough, no api_key needed."""
    email = (email or "").strip().lower()
    session = get_session()
    try:
        project = _get_project_by_api_key(session, api_key)
        user = _get_user_in_project(session, project, email=email)
        if not user:
            raise AuthSvcError("Invalid or expired code")

        v = session.query(AuthVerification).filter_by(
            user_id=user.id, purpose="password_reset", consumed=False
        ).order_by(AuthVerification.created_at.desc()).first()
        if not v or v.expires_at < utcnow() or not secrets.compare_digest(v.otp_code, (otp or "").strip()):
            raise AuthSvcError("Invalid or expired code")

        validate_password_strength(new_password, project.password_min_length, email=email)
        user.password_hash = hash_password(new_password)
        user.failed_attempts = 0
        user.lockout_count = 0
        user.locked_until = None
        v.consumed = True
        session.commit()
        return {"email": user.email, "password_reset": True}
    finally:
        session.close()


def reset_password_by_token(token: str, new_password: str) -> dict:
    """Used by the emailed reset link's landing page. The token is a
    single-use bearer capability scoped to exactly one user/purpose — no
    API key travels in the email, so a leaked/forwarded link can reset
    that one account's password and nothing else."""
    session = get_session()
    try:
        v = _find_verification_by_token(session, token, "password_reset")
        if not v or v.expires_at < utcnow():
            raise AuthSvcError("Reset link is invalid, already used, or has expired")
        user = session.query(AuthEndUser).filter_by(id=v.user_id).first()
        project = session.query(AuthProject).filter_by(id=user.project_id).first()

        validate_password_strength(new_password, project.password_min_length, email=user.email)
        v.consumed = True
        user.password_hash = hash_password(new_password)
        user.failed_attempts = 0
        user.lockout_count = 0
        user.locked_until = None
        session.commit()
        return {"email": user.email, "password_reset": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Email change — requires an active session (proof the caller already
# controls the account), verified at the NEW address before it takes
# effect, so a stolen session token alone can't quietly redirect future
# password-reset emails to an attacker's inbox without the account owner
# ever seeing a confirmation land in their existing mailbox... actually
# the confirmation goes to the NEW address by design (that's what's being
# proven); see request_email_change for the session-token requirement
# that gates who can even start this.
# ---------------------------------------------------------------------------

def request_email_change(session_token: str, new_email: str, base_link_url: str | None = None) -> dict:
    new_email = (new_email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        raise AuthSvcError("Invalid email address")

    payload = verify_session_token(session_token)
    session = get_session()
    try:
        project = _get_project_by_project_id(session, payload["project_id"])
        user = _get_user_in_project(session, project, user_id=int(payload["sub"]))
        if not user:
            raise AuthSvcError("Session no longer valid")

        clash = session.query(AuthEndUser).filter_by(project_id=project.id, email=new_email).first()
        if clash:
            raise AuthSvcError("That email is already in use")

        verification, raw_token = _issue_verification(session, project, user, "email_change", new_email=new_email)
        _deliver_verification(session, project, user, raw_token, verification.otp_code,
                               "email_change", base_link_url, to_email=new_email)
        return {"email_sent": True, "new_email": new_email}
    finally:
        session.close()


def confirm_email_change_token(token: str) -> dict:
    session = get_session()
    try:
        v = _find_verification_by_token(session, token, "email_change")
        if not v or v.expires_at < utcnow() or not v.new_email:
            raise AuthSvcError("Confirmation link is invalid, already used, or has expired")
        user = session.query(AuthEndUser).filter_by(id=v.user_id).first()
        v.consumed = True
        user.email = v.new_email
        session.commit()
        return {"email": user.email, "email_changed": True}
    finally:
        session.close()


def confirm_email_change_otp(session_token: str, otp: str) -> dict:
    payload = verify_session_token(session_token)
    session = get_session()
    try:
        project = _get_project_by_project_id(session, payload["project_id"])
        user = _get_user_in_project(session, project, user_id=int(payload["sub"]))
        if not user:
            raise AuthSvcError("Session no longer valid")
        v = session.query(AuthVerification).filter_by(
            user_id=user.id, purpose="email_change", consumed=False
        ).order_by(AuthVerification.created_at.desc()).first()
        if not v or v.expires_at < utcnow() or not v.new_email or \
                not secrets.compare_digest(v.otp_code, (otp or "").strip()):
            raise AuthSvcError("Invalid or expired code")
        v.consumed = True
        user.email = v.new_email
        session.commit()
        return {"email": user.email, "email_changed": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Admin: end-user management — the dashboard/CLI view of a project's
# registered users, with account actions. All admin-authenticated
# (require_auth at the API layer), scoped to one project throughout.
# ---------------------------------------------------------------------------

def _user_summary(user: AuthEndUser) -> dict:
    locked = bool(user.locked_until and user.locked_until > utcnow())
    return {
        "user_id": user.public_id,
        "email": user.email,
        "email_verified": user.email_verified,
        "verification_method": user.verification_method,  # otp | link | None (not yet verified)
        "disabled": user.disabled,
        "locked": locked,
        "locked_until": user.locked_until.isoformat() if locked else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def list_users(project_id: str) -> list[dict]:
    session = get_session()
    try:
        project = _get_project_by_project_id(session, project_id)
        users = session.query(AuthEndUser).filter_by(project_id=project.id) \
            .order_by(AuthEndUser.created_at.desc()).all()
        return [_user_summary(u) for u in users]
    finally:
        session.close()


def _get_user_by_public_id(session, project: AuthProject, user_id: str) -> AuthEndUser:
    user = session.query(AuthEndUser).filter_by(project_id=project.id, public_id=user_id).first()
    if not user:
        raise AuthSvcError(f"No user '{user_id}' in project '{project.project_id}'")
    return user


def admin_delete_user(project_id: str, user_id: str) -> dict:
    session = get_session()
    try:
        project = _get_project_by_project_id(session, project_id)
        user = _get_user_by_public_id(session, project, user_id)
        # Verification rows reference user_id via a FK with no cascade
        # configured at the DB level — clean them up explicitly so a
        # deleted account doesn't leave orphaned rows another user's
        # public_id could theoretically collide into later.
        session.query(AuthVerification).filter_by(user_id=user.id).delete()
        email = user.email
        session.delete(user)
        session.commit()
        return {"user_id": user_id, "email": email, "deleted": True}
    finally:
        session.close()


def admin_disable_user(project_id: str, user_id: str, disabled: bool) -> dict:
    session = get_session()
    try:
        project = _get_project_by_project_id(session, project_id)
        user = _get_user_by_public_id(session, project, user_id)
        user.disabled = disabled
        session.commit()
        return {"user_id": user_id, "email": user.email, "disabled": disabled}
    finally:
        session.close()


def admin_send_password_reset(project_id: str, user_id: str, base_link_url: str | None = None) -> dict:
    """Same delivery mechanism as forgot_password(), triggered from the
    dashboard/CLI by an admin rather than requested by the end user."""
    session = get_session()
    try:
        project = _get_project_by_project_id(session, project_id)
        user = _get_user_by_public_id(session, project, user_id)
        verification, raw_token = _issue_verification(session, project, user, "password_reset")
        _deliver_verification(session, project, user, raw_token, verification.otp_code,
                               "password_reset", base_link_url)
        return {"user_id": user_id, "email": user.email, "email_sent": True}
    finally:
        session.close()
