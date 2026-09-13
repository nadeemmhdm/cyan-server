"""
Cyan Server - Unified Client v1 API
Allows external applications, websites, and scripts to access Databases and
Storage Buckets using a single universal API key + Unique Resource ID.
"""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel

from security.dependencies import require_auth_or_api_key
from database import manager as db_manager
from storage import manager as storage_manager

router = APIRouter(prefix="/api/v1", tags=["v1"])


def _check_read_permission(auth: dict):
    perm = auth.get("permissions", "full")
    if perm == "write":
        raise HTTPException(403, "API key has write-only permissions; read/query is not allowed")


def _check_write_permission(auth: dict):
    perm = auth.get("permissions", "full")
    if perm == "read":
        raise HTTPException(403, "API key has read-only permissions; write/modify is not allowed")


# ---------------------------------------------------------------------------
# Database Endpoints (Accessed via X-API-Key + Database Unique ID)
# ---------------------------------------------------------------------------

class V1QueryRequest(BaseModel):
    sql: str
    params: list | None = None


@router.get("/database/{db_id}/status")
def v1_database_status(db_id: str, auth=Depends(require_auth_or_api_key)):
    _check_read_permission(auth)
    try:
        return db_manager.get_status(db_id)
    except db_manager.DatabaseError as e:
        raise HTTPException(404, str(e))


@router.get("/database/{db_id}/tables")
def v1_database_tables(db_id: str, auth=Depends(require_auth_or_api_key)):
    _check_read_permission(auth)
    try:
        status = db_manager.get_status(db_id)
        return {"database_id": db_id, "tables": status.get("tables", [])}
    except db_manager.DatabaseError as e:
        raise HTTPException(404, str(e))


@router.post("/database/{db_id}/query")
def v1_database_query(db_id: str, req: V1QueryRequest, auth=Depends(require_auth_or_api_key)):
    sql_stripped = req.sql.strip().upper()
    is_write = not (sql_stripped.startswith("SELECT") or sql_stripped.startswith("PRAGMA") or sql_stripped.startswith("EXPLAIN"))
    if is_write:
        _check_write_permission(auth)
    else:
        _check_read_permission(auth)

    try:
        res = db_manager.execute_query(db_id, req.sql, params=tuple(req.params) if req.params else None)
        return {
            "database_id": db_id,
            "columns": res.get("columns", []),
            "rows": res.get("rows", []),
            "row_count": res.get("row_count", 0),
        }
    except db_manager.DatabaseError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# Storage Bucket Endpoints (Accessed via X-API-Key + Storage Bucket Unique ID)
# ---------------------------------------------------------------------------

@router.get("/storage/{bucket_id}/files")
def v1_bucket_list_files(bucket_id: str, auth=Depends(require_auth_or_api_key)):
    _check_read_permission(auth)
    try:
        files = storage_manager.list_bucket_files(bucket_id)
        return {"bucket_id": bucket_id, "files": files, "total_files": len(files)}
    except storage_manager.StorageError as e:
        raise HTTPException(404, str(e))


@router.post("/storage/{bucket_id}/upload")
async def v1_bucket_upload(bucket_id: str, file: UploadFile = File(...), auth=Depends(require_auth_or_api_key)):
    _check_write_permission(auth)
    try:
        content = await file.read()
        res = storage_manager.save_bucket_file(bucket_id, file.filename, content)
        return res
    except storage_manager.StorageError as e:
        raise HTTPException(400, str(e))


@router.get("/storage/{bucket_id}/download/{filename}")
def v1_bucket_download(bucket_id: str, filename: str, auth=Depends(require_auth_or_api_key)):
    _check_read_permission(auth)
    try:
        content = storage_manager.read_bucket_file(bucket_id, filename)
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'",
            "Content-Disposition": f'attachment; filename="{filename}"',
        }
        return Response(content=content, media_type="application/octet-stream", headers=headers)
    except storage_manager.StorageError as e:
        raise HTTPException(404, str(e))


@router.delete("/storage/{bucket_id}/files/{filename}")
def v1_bucket_delete_file(bucket_id: str, filename: str, permanent: bool = False, auth=Depends(require_auth_or_api_key)):
    _check_write_permission(auth)
    try:
        storage_manager.delete_bucket_file(bucket_id, filename, permanent=permanent)
        return {"success": True, "bucket_id": bucket_id, "filename": filename, "deleted": True}
    except storage_manager.StorageError as e:
        raise HTTPException(404, str(e))
