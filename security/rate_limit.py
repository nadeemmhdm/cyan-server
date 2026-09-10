"""
Cyan Server - Rate Limiting & Account Lockout
Real, in-process sliding-window rate limiting + per-username lockout after
repeated failed logins. In-memory (per agent process) — sufficient for a
single-node local/LAN agent; documented as a known limitation for
multi-instance deployments.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

MAX_ATTEMPTS_PER_WINDOW = 10
WINDOW_SECONDS = 60

LOCKOUT_THRESHOLD = 5          # failed attempts
LOCKOUT_SECONDS = 300           # 5 minutes

_ip_attempts: dict[str, deque] = defaultdict(deque)
_failed_logins: dict[str, list[float]] = defaultdict(list)
_locked_until: dict[str, float] = {}


class RateLimitExceeded(Exception):
    pass


class AccountLocked(Exception):
    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Account locked. Retry in {retry_after_seconds:.0f}s")


def check_rate_limit(source_ip: str) -> None:
    """Sliding-window IP rate limit — protects the login endpoint from
    brute force regardless of which username is targeted."""
    now = time.time()
    attempts = _ip_attempts[source_ip]
    while attempts and now - attempts[0] > WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= MAX_ATTEMPTS_PER_WINDOW:
        raise RateLimitExceeded(f"Too many requests from {source_ip}")
    attempts.append(now)


def check_lockout(username: str) -> None:
    locked_until = _locked_until.get(username)
    if locked_until and time.time() < locked_until:
        raise AccountLocked(locked_until - time.time())
    if locked_until and time.time() >= locked_until:
        _locked_until.pop(username, None)
        _failed_logins[username] = []


def record_failed_login(username: str) -> None:
    now = time.time()
    attempts = _failed_logins[username]
    attempts.append(now)
    recent = [t for t in attempts if now - t < LOCKOUT_SECONDS]
    _failed_logins[username] = recent
    if len(recent) >= LOCKOUT_THRESHOLD:
        _locked_until[username] = now + LOCKOUT_SECONDS


def record_successful_login(username: str) -> None:
    _failed_logins.pop(username, None)
    _locked_until.pop(username, None)
