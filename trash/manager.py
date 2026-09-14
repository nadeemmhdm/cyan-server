# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Cyan Server - Trash / Recycle Bin
Nothing deleted from storage, websites, or (in future) databases is gone
immediately — it moves to a trash area, stays restorable for
RETENTION_DAYS, and is only permanently purged after that (or on demand
via `cyan trash empty`). This module owns the move-to-trash and
restore-from-trash mechanics; storage/manager.py and web/manager.py call
into it instead of deleting content directly.
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from core.database import TrashItem, get_session

RETENTION_DAYS = 30


def get_trash_dir() -> Path:
    """Re-read CYAN_DATA_DIR on every call — see web/manager.py's
    _data_dir() docstring for why a cached path is a real bug."""
    d = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server")) / "trash"
    d.mkdir(parents=True, exist_ok=True)
    return d


class TrashError(Exception):
    pass


def move_to_trash(item_type: str, name: str, original_path: str,
                   source_fs_path: Path, metadata: dict | None = None) -> TrashItem:
    """Moves the real file/folder at source_fs_path into the trash area
    and records it. source_fs_path must exist and be movable (same
    filesystem is fastest; shutil.move handles cross-filesystem too)."""
    if not source_fs_path.exists():
        raise TrashError(f"Nothing to trash at {source_fs_path}")

    trash_id = str(uuid.uuid4())
    trash_path = get_trash_dir() / trash_id
    shutil.move(str(source_fs_path), str(trash_path))

    now = datetime.utcnow()
    session = get_session()
    try:
        item = TrashItem(
            item_type=item_type, name=name, original_path=original_path,
            trash_path=str(trash_path), deleted_at=now,
            expires_at=now + timedelta(days=RETENTION_DAYS),
        )
        if metadata:
            import json
            item.metadata_json = json.dumps(metadata)
        session.add(item)
        session.commit()
        session.refresh(item)
        return item
    finally:
        session.close()


def list_trash(item_type: str | None = None) -> list[TrashItem]:
    session = get_session()
    try:
        q = session.query(TrashItem)
        if item_type:
            q = q.filter_by(item_type=item_type)
        return q.order_by(TrashItem.deleted_at.desc()).all()
    finally:
        session.close()


def get_trash_item(trash_id: int) -> TrashItem:
    session = get_session()
    try:
        item = session.query(TrashItem).filter_by(id=trash_id).first()
        if not item:
            raise TrashError(f"Trash item {trash_id} not found")
        return item
    finally:
        session.close()


def restore(trash_id: int, restore_to: Path) -> TrashItem:
    """Moves an item's content back out of trash to restore_to, and
    removes the trash record. Caller (storage/web manager) is responsible
    for knowing what restore_to should be and re-registering the item in
    its own table if needed (e.g. re-adding a Website row)."""
    item = get_trash_item(trash_id)
    trash_path = Path(item.trash_path)
    if not trash_path.exists():
        raise TrashError("Trash content is missing on disk (may have been purged already)")

    restore_to.parent.mkdir(parents=True, exist_ok=True)
    if restore_to.exists():
        raise TrashError(f"Cannot restore — something already exists at {restore_to}")
    shutil.move(str(trash_path), str(restore_to))

    session = get_session()
    try:
        row = session.query(TrashItem).filter_by(id=trash_id).first()
        if row:
            session.delete(row)
            session.commit()
    finally:
        session.close()
    return item


def permanently_delete(trash_id: int) -> None:
    item = get_trash_item(trash_id)
    trash_path = Path(item.trash_path)
    if trash_path.exists():
        if trash_path.is_dir():
            shutil.rmtree(trash_path)
        else:
            trash_path.unlink()
    session = get_session()
    try:
        row = session.query(TrashItem).filter_by(id=trash_id).first()
        if row:
            session.delete(row)
            session.commit()
    finally:
        session.close()


def purge_expired() -> list[str]:
    """Permanently removes anything past its retention period. Called by
    a background thread (like auto-update) and also runnable on demand."""
    now = datetime.utcnow()
    purged = []
    for item in list_trash():
        if item.expires_at <= now:
            name = item.name
            permanently_delete(item.id)
            purged.append(name)
    return purged


def empty_trash() -> list[str]:
    """`cyan trash empty` — permanently deletes everything in trash right
    now, regardless of retention period. Explicit user action, not
    automatic."""
    names = []
    for item in list_trash():
        names.append(item.name)
        permanently_delete(item.id)
    return names


# ---------------------------------------------------------------------------
# Background auto-purge (mirrors core/update.py's auto-update thread)
# ---------------------------------------------------------------------------

def start_auto_purge_thread():
    import threading
    import time as _time

    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                purge_expired()
            except Exception:  # noqa: BLE001 — background thread must never crash the agent
                pass
            for _ in range(6 * 60):  # check every 10s whether to stop; purge once/hour
                if stop_event.is_set():
                    return
                _time.sleep(10)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return stop_event
