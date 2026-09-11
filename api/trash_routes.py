from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from security.dependencies import require_auth
from trash import manager as trash_manager
from storage.manager import restore_from_trash as storage_restore, StorageError

router = APIRouter(prefix="/api/trash", tags=["trash"])


def _serialize(item) -> dict:
    return {
        "id": item.id, "item_type": item.item_type, "name": item.name,
        "original_path": item.original_path, "deleted_at": item.deleted_at.isoformat(),
        "expires_at": item.expires_at.isoformat(),
    }


@router.get("")
def list_trash(item_type: str = None, _=Depends(require_auth)):
    return [_serialize(i) for i in trash_manager.list_trash(item_type)]


@router.post("/{trash_id}/restore")
def restore_item(trash_id: int, _=Depends(require_auth)):
    item = trash_manager.get_trash_item(trash_id)
    try:
        if item.item_type == "storage":
            restored_path = storage_restore(trash_id)
            return {"success": True, "restored_to": restored_path}
        raise HTTPException(400, f"Restore not yet implemented for item_type '{item.item_type}'")
    except (trash_manager.TrashError, StorageError) as e:
        raise HTTPException(400, str(e))


@router.delete("/{trash_id}")
def delete_permanently(trash_id: int, _=Depends(require_auth)):
    try:
        trash_manager.permanently_delete(trash_id)
        return {"success": True}
    except trash_manager.TrashError as e:
        raise HTTPException(404, str(e))


@router.post("/empty")
def empty_trash(_=Depends(require_auth)):
    names = trash_manager.empty_trash()
    return {"deleted": names}


@router.post("/purge-expired")
def purge_expired(_=Depends(require_auth)):
    """Manually trigger the same purge the background thread runs on a
    schedule — useful for testing or an immediate cleanup."""
    names = trash_manager.purge_expired()
    return {"purged": names}
