# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Cyan Server - TOTP Two-Factor Authentication (RFC 6238)
Pure Python implementation with zero external dependencies:
- HMAC-SHA1 calculation
- 30-second time-step interval
- 6-digit one-time codes
- Base32 secret generation & decoding
- Clock drift tolerance window (±1 step / 30s)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
import urllib.parse


def generate_secret(length: int = 32) -> str:
    """Generate a high-entropy base32 secret string (RFC 4648 without padding)."""
    # 20 bytes = 160 bits (recommended for HMAC-SHA1)
    random_bytes = secrets.token_bytes(20)
    return base64.b32encode(random_bytes).decode("ascii").replace("=", "")


def _decode_secret(secret: str) -> bytes:
    """Normalize and decode a base32 secret, adding required '=' padding."""
    clean = secret.strip().replace(" ", "").upper()
    missing_padding = len(clean) % 8
    if missing_padding:
        clean += "=" * (8 - missing_padding)
    return base64.b32decode(clean, casefold=True)


def get_totp_code(secret: str, for_time: float | None = None, interval: int = 30) -> str:
    """Calculate the 6-digit TOTP code for a given timestamp (default: now)."""
    if for_time is None:
        for_time = time.time()
    
    key = _decode_secret(secret)
    # Counter is the number of 30-second intervals since Unix epoch
    counter = int(for_time // interval)
    # Pack counter as 8-byte big-endian integer
    msg = struct.pack(">Q", counter)
    
    # HMAC-SHA1 hash
    h = hmac.new(key, msg, hashlib.sha1).digest()
    
    # Dynamic truncation (RFC 4226)
    offset = h[-1] & 0x0F
    code_int = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    
    # 6 digits with leading zero padding
    code_str = str(code_int % 1000000).zfill(6)
    return code_str


def verify_totp(secret: str, code: str, window: int = 1, interval: int = 30) -> bool:
    """Verify a user-provided 6-digit code against the secret.
    Allows clock drift tolerance within ±window intervals (default ±1 interval = ±30 seconds).
    """
    if not secret or not code:
        return False
    
    clean_code = code.strip().replace(" ", "")
    if len(clean_code) != 6 or not clean_code.isdigit():
        return False
    
    now = time.time()
    for drift in range(-window, window + 1):
        test_time = now + (drift * interval)
        if hmac.compare_digest(get_totp_code(secret, test_time, interval), clean_code):
            return True
            
    return False


def get_otpauth_uri(secret: str, account_name: str, issuer: str = "Cyan Server") -> str:
    """Generate the standard otpauth:// URL scanned by Google Authenticator, Authy, etc."""
    label = f"{issuer}:{account_name}"
    params = {
        "secret": secret.strip().replace(" ", "").upper(),
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": "6",
        "period": "30",
    }
    return f"otpauth://totp/{urllib.parse.quote(label)}?{urllib.parse.urlencode(params)}"
