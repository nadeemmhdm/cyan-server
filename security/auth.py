"""
Cyan Server - Security / Auth
Real bcrypt password hashing + JWT session tokens. No plaintext passwords,
no fake "always authorized" bypass.
"""
from __future__ import annotations

import datetime
import os
import secrets
from pathlib import Path

import bcrypt
import jwt

from core.database import User, get_session

DATA_DIR = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SECRET_PATH = DATA_DIR / ".cyan_secret"

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 12


def get_or_create_secret() -> str:
    """Persistent per-install secret, used to sign JWTs. Generated once,
    written with 0600 perms — this is what the installer also generates."""
    if SECRET_PATH.exists():
        return SECRET_PATH.read_text().strip()
    secret = secrets.token_hex(32)
    SECRET_PATH.write_text(secret)
    try:
        SECRET_PATH.chmod(0o600)
    except OSError:
        pass  # best-effort on platforms without POSIX perms (Windows)
    return secret


def hash_password(password: str) -> str:
    # bcrypt has a hard 72-byte input limit; truncate defensively so long
    # passphrases don't raise instead of silently truncating.
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], password_hash.encode())
    except ValueError:
        return False


def ensure_default_admin(username: str = "admin", password: str | None = None) -> tuple[str, str]:
    """Creates the admin user on first run if none exists. Returns
    (username, password) — password is only returned when freshly
    generated, so the installer/CLI can show it to the user exactly once."""
    session = get_session()
    try:
        existing = session.query(User).filter_by(username=username).first()
        if existing:
            return username, ""
        generated = password or secrets.token_urlsafe(12)
        user = User(username=username, password_hash=hash_password(generated), role="admin")
        session.add(user)
        session.commit()
        return username, generated
    finally:
        session.close()


def authenticate(username: str, password: str) -> User | None:
    session = get_session()
    try:
        user = session.query(User).filter_by(username=username).first()
        if user and verify_password(password, user.password_hash):
            return user
        return None
    finally:
        session.close()


def create_token(user: User) -> str:
    payload = {
        "sub": user.username,
        "role": user.role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, get_or_create_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_or_create_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
