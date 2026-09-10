"""
Cyan Server - Update Manager (spec: `cyan update`)
Real git-based self-update: checks the local checkout against its remote,
shows what would change, and applies it only on confirmation (same
plan-then-confirm pattern as PackageManager.install()). Requires the
install to be a git checkout — that's true for anything installed via
installer/install.sh or installer/install.ps1.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.version import VERSION

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
    user check_for_update()'s result and gotten confirmation first."""
    status = check_for_update()
    if status.up_to_date:
        return "Already up to date."
    if not status.is_git_repo:
        raise UpdateError("Not a git checkout — cannot self-update. Reinstall via the installer.")

    result = _run_git(["merge", "--ff-only", "origin/HEAD"])
    if result.returncode != 0:
        raise UpdateError(f"Update failed (not a fast-forward?): {result.stderr}")
    return f"Updated {status.commits_behind} commit(s). Restart the agent to apply."
