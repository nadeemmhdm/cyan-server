"""
Cyan Server - Backup Manager (spec section 19: Backup)
Real point-in-time snapshots of the whole install: the database (users,
website/app/tunnel/database config, everything), the Caddyfile, deployed
website source folders, and managed SQLite database files. Storage
content is opt-in (can be large) — off by default.

Backup creation is safe to run while the agent is live (uses SQLite's own
backup API for a consistent DB snapshot instead of copying the file raw).
Restore is NOT something the agent does to itself while running — it's a
CLI-only operation that requires the agent to be stopped first, because
overwriting cyan.db out from under a live SQLAlchemy connection pool
doesn't reliably take effect until reconnect anyway. See cli/main.py's
`backup restore` command.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from core.database import BackupConfig, get_session, DB_PATH

def _data_dir() -> Path:
    """Re-read CYAN_DATA_DIR on every call — see web/manager.py's
    _data_dir() docstring for why a cached path is a real bug."""
    return Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))


class BackupError(Exception):
    pass


def get_backup_config() -> BackupConfig:
    session = get_session()
    try:
        cfg = session.query(BackupConfig).first()
        if not cfg:
            cfg = BackupConfig()
            session.add(cfg)
            session.commit()
            session.refresh(cfg)
        return cfg
    finally:
        session.close()


def set_backup_config(**kwargs) -> BackupConfig:
    session = get_session()
    try:
        cfg = session.query(BackupConfig).first()
        if not cfg:
            cfg = BackupConfig()
            session.add(cfg)
        for k, v in kwargs.items():
            if v is not None:
                setattr(cfg, k, v)
        session.commit()
        session.refresh(cfg)
        return cfg
    finally:
        session.close()


def _safe_sqlite_snapshot(dest_path: Path) -> None:
    """Uses SQLite's own backup API rather than copying the .sqlite file
    directly — a raw file copy taken mid-write can capture a torn/corrupt
    page; the backup API produces a consistent snapshot regardless of
    concurrent writes from the live agent."""
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(dest_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def create_backup(destination: Path | None = None, include_storage: bool | None = None) -> Path:
    cfg = get_backup_config()
    dest_dir = destination or (Path(cfg.destination_dir) if cfg.destination_dir else (_data_dir() / "backups"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    if include_storage is None:
        include_storage = cfg.include_storage

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    archive_path = dest_dir / f"cyan-backup-{timestamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "cyan.db"
        _safe_sqlite_snapshot(tmp_db)

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_db, arcname="cyan.db")
            if (_data_dir() / "Caddyfile").exists():
                tar.add(_data_dir() / "Caddyfile", arcname="Caddyfile")
            if (_data_dir() / "sites").exists():
                tar.add(_data_dir() / "sites", arcname="sites")
            if (_data_dir() / "databases").exists():
                tar.add(_data_dir() / "databases", arcname="databases")
            if include_storage and (_data_dir() / "storage").exists():
                tar.add(_data_dir() / "storage", arcname="storage")

    set_backup_config(last_backup_at=datetime.utcnow(), last_backup_result="success")
    return archive_path


def list_backups(destination: Path | None = None) -> list[dict]:
    cfg = get_backup_config()
    dest_dir = destination or (Path(cfg.destination_dir) if cfg.destination_dir else (_data_dir() / "backups"))
    if not dest_dir.exists():
        return []
    backups = []
    for f in sorted(dest_dir.glob("cyan-backup-*.tar.gz"), reverse=True):
        stat = f.stat()
        backups.append({
            "filename": f.name, "path": str(f), "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return backups


def prune_backups(destination: Path | None = None, retention_count: int | None = None) -> list[str]:
    cfg = get_backup_config()
    retention = retention_count if retention_count is not None else cfg.retention_count
    backups = list_backups(destination)
    removed = []
    for b in backups[retention:]:  # list_backups is newest-first
        Path(b["path"]).unlink(missing_ok=True)
        removed.append(b["filename"])
    return removed


def _validate_tar_member(member: tarfile.TarInfo, base: Path) -> bool:
    """Reject path-traversal / tarbomb members (e.g. '../../etc/passwd')
    before extraction — Python's tarfile.extractall(filter='data') covers
    most of this on 3.12+, but we check explicitly too since this backup
    format is also meant to be readable/writable by older Python."""
    target = (base / member.name).resolve()
    return base.resolve() in target.parents or target == base.resolve()


def restore_backup(backup_path: Path, data_dir: Path | None = None) -> dict:
    """Extracts a backup archive over data_dir, REPLACING cyan.db,
    Caddyfile, sites/, and databases/ (and storage/ if present in the
    archive). Intended to be called with the agent stopped — see the
    module docstring. Existing content at those paths is moved aside to
    a `.pre-restore-<timestamp>` folder rather than deleted outright, in
    case the restore itself needs undoing."""
    if not backup_path.exists():
        raise BackupError(f"Backup file not found: {backup_path}")

    target_dir = data_dir or _data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(backup_path, "r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            if not _validate_tar_member(m, target_dir):
                raise BackupError(f"Refusing to restore unsafe path in archive: {m.name}")

        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        preserved = []
        for name in ("cyan.db", "Caddyfile", "sites", "databases", "storage"):
            existing = target_dir / name
            if existing.exists() and any(m.name == name or m.name.startswith(f"{name}/") for m in members):
                backup_aside = target_dir / f".pre-restore-{timestamp}" / name
                backup_aside.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(existing), str(backup_aside))
                preserved.append(name)

        try:
            tar.extractall(target_dir, filter="data")
        except TypeError:
            # Python <3.12 doesn't support the filter= kwarg — we already
            # validated every member above, so plain extractall is safe here.
            tar.extractall(target_dir)

        # The 'data' extraction filter (and some archive/tempfile
        # permission combinations without it) can leave restored files
        # without owner-write permission, which breaks SQLite the moment
        # the agent tries to write to the restored cyan.db. Normalize
        # permissions on everything this restore just wrote.
        extracted_top_names = {m.name.split("/")[0] for m in members}
        for name in extracted_top_names:
            p = target_dir / name
            if p.is_file():
                p.chmod(0o644)
            elif p.is_dir():
                for sub in p.rglob("*"):
                    sub.chmod(0o755 if sub.is_dir() else 0o644)

    result = {
        "restored_from": str(backup_path),
        "preserved_previous_state_at": f".pre-restore-{timestamp}" if preserved else None,
    }

    # Critical: SQLAlchemy's connection pool (core.database.engine) may
    # still hold sqlite3 connections opened against the pre-restore file.
    # Those stale connections keep working against the old, now-moved-
    # aside inode rather than erroring cleanly — and can produce
    # confusing "attempt to write a readonly database" failures on the
    # next write once SQLite's journal handling gets involved. Dispose
    # the pool so every connection from here on is opened fresh against
    # the just-restored file.
    from core.database import engine as _engine
    _engine.dispose()

    return result


# ---------------------------------------------------------------------------
# Background auto-backup (same pattern as auto-update / trash auto-purge)
# ---------------------------------------------------------------------------

def start_auto_backup_thread():
    import threading
    import time as _time

    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            cfg = get_backup_config()
            if cfg.auto_enabled:
                try:
                    create_backup()
                    prune_backups()
                except Exception as e:  # noqa: BLE001 — never crash the agent
                    set_backup_config(last_backup_result=f"error: {e}")
            interval_seconds = max(3600, get_backup_config().interval_hours * 3600)
            for _ in range(interval_seconds // 10):
                if stop_event.is_set():
                    return
                _time.sleep(10)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return stop_event
