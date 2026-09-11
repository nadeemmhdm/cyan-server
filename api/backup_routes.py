from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth, require_admin
from backup import manager as backup_manager

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("")
def list_backups(_=Depends(require_auth)):
    return backup_manager.list_backups()


class CreateBackupRequest(BaseModel):
    include_storage: bool | None = None


@router.post("")
def create_backup(req: CreateBackupRequest, _=Depends(require_admin)):
    try:
        path = backup_manager.create_backup(include_storage=req.include_storage)
        return {"filename": path.name, "path": str(path)}
    except backup_manager.BackupError as e:
        raise HTTPException(400, str(e))


@router.get("/config")
def get_config(_=Depends(require_auth)):
    cfg = backup_manager.get_backup_config()
    return {
        "destination_dir": cfg.destination_dir, "retention_count": cfg.retention_count,
        "interval_hours": cfg.interval_hours, "auto_enabled": cfg.auto_enabled,
        "include_storage": cfg.include_storage,
        "last_backup_at": cfg.last_backup_at.isoformat() if cfg.last_backup_at else None,
        "last_backup_result": cfg.last_backup_result,
    }


class UpdateConfigRequest(BaseModel):
    destination_dir: str | None = None
    retention_count: int | None = None
    interval_hours: int | None = None
    auto_enabled: bool | None = None
    include_storage: bool | None = None


@router.post("/config")
def update_config(req: UpdateConfigRequest, _=Depends(require_admin)):
    cfg = backup_manager.set_backup_config(**req.model_dump(exclude_unset=True))
    return {
        "destination_dir": cfg.destination_dir, "retention_count": cfg.retention_count,
        "interval_hours": cfg.interval_hours, "auto_enabled": cfg.auto_enabled,
        "include_storage": cfg.include_storage,
    }


@router.delete("/{filename}")
def delete_backup(filename: str, _=Depends(require_admin)):
    from pathlib import Path
    for b in backup_manager.list_backups():
        if b["filename"] == filename:
            Path(b["path"]).unlink()
            return {"success": True}
    raise HTTPException(404, f"Backup '{filename}' not found")

# NOTE: intentionally no POST /restore endpoint here. Restoring overwrites
# cyan.db out from under the running agent's own SQLAlchemy connection
# pool -- see backup/manager.py's module docstring. Restore is a CLI-only
# command (`cyan backup restore`) that stops the agent first.
