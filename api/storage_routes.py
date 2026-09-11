from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel

from security.dependencies import require_auth
from storage import manager as storage_manager

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/list")
def list_dir(path: str = "", _=Depends(require_auth)):
    try:
        return {"path": path, "entries": storage_manager.list_dir(path)}
    except storage_manager.StorageError as e:
        raise HTTPException(400, str(e))


@router.get("/usage")
def usage(_=Depends(require_auth)):
    return {"used_gb": storage_manager.usage_gb(), "quota_gb": storage_manager.quota_gb()}


class MkdirRequest(BaseModel):
    path: str


@router.post("/mkdir")
def mkdir(req: MkdirRequest, _=Depends(require_auth)):
    try:
        storage_manager.make_dir(req.path)
        return {"success": True}
    except storage_manager.StorageError as e:
        raise HTTPException(400, str(e))


@router.delete("/item")
def delete_item(path: str, permanent: bool = False, _=Depends(require_auth)):
    try:
        storage_manager.delete_path(path, permanent=permanent)
        return {"success": True, "permanent": permanent}
    except storage_manager.StorageError as e:
        raise HTTPException(400, str(e))


@router.post("/upload")
async def upload(path: str = Form(""), file: UploadFile = File(...), _=Depends(require_auth)):
    try:
        content = await file.read()
        storage_manager.save_upload(path, file.filename, content)
        return {"success": True, "filename": file.filename, "size_bytes": len(content)}
    except storage_manager.StorageError as e:
        raise HTTPException(400, str(e))


@router.get("/download")
def download(path: str, _=Depends(require_auth)):
    try:
        content = storage_manager.read_file(path)
        return Response(content=content, media_type="application/octet-stream")
    except storage_manager.StorageError as e:
        raise HTTPException(400, str(e))


class ShareLinkRequest(BaseModel):
    path: str
    expires_hours: float | None = 24


@router.post("/share")
def create_share(req: ShareLinkRequest, _=Depends(require_auth)):
    try:
        token = storage_manager.create_share_link(req.path, req.expires_hours)
        return {"token": token}
    except storage_manager.StorageError as e:
        raise HTTPException(400, str(e))


@router.get("/share")
def list_shares(_=Depends(require_auth)):
    return {"links": storage_manager.list_share_links()}


@router.get("/share/{token}")
def resolve_share(token: str):
    """Public — no auth required, this is how recipients fetch a shared file."""
    try:
        relative = storage_manager.resolve_share_link(token)
        content = storage_manager.read_file(relative)
        return Response(content=content, media_type="application/octet-stream")
    except storage_manager.StorageError as e:
        raise HTTPException(404, str(e))
