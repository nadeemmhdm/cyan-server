# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Cyan Server - Update Manager (spec: `cyan update`)
Real git-based self-update: checks the local checkout against its remote,
shows what would change, and applies it only on confirmation (same
plan-then-confirm pattern as PackageManager.install()) — unless auto_apply
is explicitly enabled, in which case a background thread checks on an
interval and applies fast-forward-only updates automatically. Requires the
install to be a git checkout — that's true for anything installed via
installer/install.sh or installer/install.ps1.
"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.version import VERSION
from core.database import UpdateConfig, get_session

REPO_ROOT = Path(__file__).resolve().parent.parent


class UpdateError(Exception):
    pass


@dataclass
class UpdateStatus:
    current_version: str
    is_git_repo: bool
    up_to_date: bool
    local_commit: str | None
    remote_commit: str | None
    commits_behind: int
    changelog: list[str]

    @property
    def is_security_update(self) -> bool:
        """True if any pending commit's message flags a security fix —
        conventionally '[security]' or 'CVE-' in the subject line. Used
        to bypass the auto_apply toggle: security fixes apply even when
        the user has auto-apply turned off (see _auto_update_loop)."""
        markers = ("[security]", "cve-")
        return any(any(m in line.lower() for m in markers) for line in self.changelog)


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=REPO_ROOT,
                           capture_output=True, text=True, timeout=30)


def check_for_update() -> UpdateStatus:
    """Real check: fetches from origin (if any) and compares HEAD to
    origin/HEAD. Never applies anything — that's a separate, explicit step."""
    is_repo = (REPO_ROOT / ".git").exists()
    if not is_repo:
        return UpdateStatus(VERSION, False, True, None, None, 0, [])

    local = _run_git(["rev-parse", "HEAD"])
    local_commit = local.stdout.strip() if local.returncode == 0 else None

    fetch = _run_git(["fetch", "origin"])
    if fetch.returncode != 0:
        # No reachable remote (e.g. local-only checkout). Report what we
        # know without pretending to have checked upstream.
        return UpdateStatus(VERSION, True, True, local_commit, None, 0, [])

    remote = _run_git(["rev-parse", "origin/HEAD"])
    if remote.returncode != 0:
        # origin/HEAD not set — fall back to the current branch's upstream
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        remote = _run_git(["rev-parse", f"origin/{branch.stdout.strip()}"])
    remote_commit = remote.stdout.strip() if remote.returncode == 0 else None

    if not remote_commit or remote_commit == local_commit:
        return UpdateStatus(VERSION, True, True, local_commit, remote_commit, 0, [])

    count = _run_git(["rev-list", "--count", f"{local_commit}..{remote_commit}"])
    commits_behind = int(count.stdout.strip()) if count.returncode == 0 else 0

    log = _run_git(["log", "--oneline", f"{local_commit}..{remote_commit}"])
    changelog = log.stdout.strip().splitlines() if log.returncode == 0 else []

    return UpdateStatus(VERSION, True, False, local_commit, remote_commit,
                         commits_behind, changelog)


def apply_update() -> str:
    """Pulls the previously-fetched changes. Caller must have shown the
    user check_for_update()'s result and gotten confirmation first —
    unless called from the auto-update thread, which only ever does
    fast-forward merges (never rewrites history, never force-pushes)."""
    status = check_for_update()
    if status.up_to_date:
        return "Already up to date."
    if not status.is_git_repo:
        raise UpdateError("Not a git checkout — cannot self-update. Reinstall via the installer.")

    result = _run_git(["merge", "--ff-only", "origin/HEAD"])
    if result.returncode != 0:
        raise UpdateError(f"Update failed (not a fast-forward?): {result.stderr}")
    return f"Updated {status.commits_behind} commit(s). Restart the agent to apply."


# ---------------------------------------------------------------------------
# Auto-update: config + background thread
# ---------------------------------------------------------------------------

def get_update_config() -> UpdateConfig:
    session = get_session()
    try:
        cfg = session.query(UpdateConfig).first()
        if not cfg:
            cfg = UpdateConfig(auto_check=True, auto_apply=False, check_interval_minutes=60)
            session.add(cfg)
            session.commit()
            session.refresh(cfg)
        return cfg
    finally:
        session.close()


def set_update_config(auto_check: bool | None = None, auto_apply: bool | None = None,
                       check_interval_minutes: int | None = None) -> UpdateConfig:
    session = get_session()
    try:
        cfg = session.query(UpdateConfig).first()
        if not cfg:
            cfg = UpdateConfig()
            session.add(cfg)
        if auto_check is not None:
            cfg.auto_check = auto_check
        if auto_apply is not None:
            cfg.auto_apply = auto_apply
        if check_interval_minutes is not None:
            cfg.check_interval_minutes = check_interval_minutes
        session.commit()
        session.refresh(cfg)
        return cfg
    finally:
        session.close()


def _record_check_result(result: str):
    session = get_session()
    try:
        cfg = session.query(UpdateConfig).first()
        if cfg:
            cfg.last_checked_at = datetime.utcnow()
            cfg.last_check_result = result
            session.commit()
    finally:
        session.close()


def _auto_update_loop(stop_event: threading.Event):
    """Runs in a daemon thread started by the agent. Sleeps in short
    increments so it can react to interval changes and shut down promptly
    rather than blocking on one long sleep."""
    while not stop_event.is_set():
        cfg = get_update_config()
        if cfg.auto_check:
            try:
                status = check_for_update()
                if status.is_security_update:
                    _record_check_result("security_update_available")
                else:
                    _record_check_result("up_to_date" if status.up_to_date else "update_available")

                # Security fixes apply regardless of the auto_apply toggle —
                # a user who's turned auto-apply off still gets a vulnerable
                # version patched automatically, since that risk outweighs
                # the "I want to control when updates land" preference the
                # toggle exists for. Non-security updates still respect it.
                if status.commits_behind and (cfg.auto_apply or status.is_security_update):
                    apply_update()
            except Exception as e:  # noqa: BLE001 — background thread must never crash the agent
                _record_check_result(f"error: {e}")
        interval_seconds = max(60, get_update_config().check_interval_minutes * 60)
        for _ in range(interval_seconds // 5):
            if stop_event.is_set():
                return
            time.sleep(5)


def start_auto_update_thread() -> threading.Event:
    stop_event = threading.Event()
    thread = threading.Thread(target=_auto_update_loop, args=(stop_event,), daemon=True)
    thread.start()
    return stop_event
