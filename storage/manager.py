"""
Cyan Server - Storage Server
Real file operations against a configurable, platform-independent storage
root (spec section 6). Applications/users only ever get access to
subdirectories they're explicitly granted (spec section 15) — this module
enforces path-traversal protection on every call.
"""
from __future__ import annotations

import os
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from core.database import StorageConfig, ShareLink, get_session

def _default_root() -> Path:
    """Re-read CYAN_DATA_DIR on every call — see web/manager.py's
    _data_dir() docstring for why a cached path is a real bug."""
    return Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server")) / "storage"


class StorageError(Exception):
    pass


def get_root() -> Path:
    session = get_session()
    try:
        cfg = session.query(StorageConfig).first()
        root = Path(cfg.root_path) if cfg else _default_root()
    finally:
        session.close()
    root.mkdir(parents=True, exist_ok=True)
    return root


def set_root(path: str, quota_gb: float | None = None) -> Path:
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    session = get_session()
    try:
        cfg = session.query(StorageConfig).first()
        if cfg:
            cfg.root_path = str(root)
            cfg.quota_gb = quota_gb
        else:
            cfg = StorageConfig(root_path=str(root), quota_gb=quota_gb)
            session.add(cfg)
        session.commit()
    finally:
        session.close()
    return root


def _safe_path(relative: str) -> Path:
    """Resolve a user-supplied relative path against the storage root,
    rejecting any attempt to escape it (path traversal protection)."""
    root = get_root().resolve()
    candidate = (root / relative.lstrip("/")).resolve()
    if root not in candidate.parents and candidate != root:
        raise StorageError("Path traversal rejected")
    return candidate


def restore_from_trash(trash_id: int) -> str:
    """Restore a storage item back to its original location. Raises if
    something now occupies that path (caller should catch and let the
    user choose a different destination if needed)."""
    from trash.manager import restore as trash_restore, get_trash_item, TrashError
    item = get_trash_item(trash_id)
    if item.item_type != "storage":
        raise StorageError(f"Trash item {trash_id} is not a storage item")
    restore_to = _safe_path(item.original_path)
    try:
        trash_restore(trash_id, restore_to)
    except TrashError as e:
        raise StorageError(str(e))
    return item.original_path


def usage_gb() -> float:
    root = get_root()
    total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    return round(total / (1024 ** 3), 4)


def quota_gb() -> float | None:
    session = get_session()
    try:
        cfg = session.query(StorageConfig).first()
        return cfg.quota_gb if cfg else None
    finally:
        session.close()


def list_dir(relative: str = "") -> list[dict]:
    target = _safe_path(relative)
    if not target.exists():
        raise StorageError("Path does not exist")
    if not target.is_dir():
        raise StorageError("Path is not a directory")
    entries = []
    for item in sorted(target.iterdir()):
        stat = item.stat()
        entries.append({
            "name": item.name,
            "is_dir": item.is_dir(),
            "size_bytes": stat.st_size if item.is_file() else None,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def make_dir(relative: str) -> None:
    target = _safe_path(relative)
    target.mkdir(parents=True, exist_ok=True)


def delete_path(relative: str, permanent: bool = False) -> None:
    """By default, moves the file/folder to trash (30-day retention,
    restorable via `cyan trash restore`) instead of deleting it outright.
    Pass permanent=True to skip trash entirely."""
    target = _safe_path(relative)
    if not target.exists():
        raise StorageError("Path does not exist")

    if permanent:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return

    from trash.manager import move_to_trash
    move_to_trash("storage", target.name, relative, target)


def save_upload(relative_dir: str, filename: str, content: bytes) -> None:
    filename = os.path.basename(filename)  # strip any path components
    quota = quota_gb()
    if quota is not None:
        projected = usage_gb() + len(content) / (1024 ** 3)
        if projected > quota:
            raise StorageError(f"Upload would exceed quota ({quota} GB)")
    target_dir = _safe_path(relative_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / filename).write_bytes(content)


def read_file(relative: str) -> bytes:
    target = _safe_path(relative)
    if not target.is_file():
        raise StorageError("Not a file")
    return target.read_bytes()


def create_share_link(relative: str, expires_hours: float | None = 24) -> str:
    target = _safe_path(relative)
    if not target.exists():
        raise StorageError("Path does not exist")
    token = secrets.token_urlsafe(24)
    expires_at = (datetime.utcnow() + timedelta(hours=expires_hours)) if expires_hours else None
    session = get_session()
    try:
        session.add(ShareLink(token=token, relative_path=relative, expires_at=expires_at))
        session.commit()
    finally:
        session.close()
    return token


def resolve_share_link(token: str) -> str:
    """Returns the relative path for a valid, non-expired share token."""
    session = get_session()
    try:
        link = session.query(ShareLink).filter_by(token=token).first()
        if not link:
            raise StorageError("Invalid share link")
        if link.expires_at and link.expires_at < datetime.utcnow():
            raise StorageError("Share link expired")
        return link.relative_path
    finally:
        session.close()


def list_share_links() -> list[dict]:
    session = get_session()
    try:
        links = session.query(ShareLink).all()
        return [{
            "token": l.token, "path": l.relative_path,
            "expires_at": l.expires_at.isoformat() if l.expires_at else None,
            "created_at": l.created_at.isoformat(),
        } for l in links]
    finally:
        session.close()
