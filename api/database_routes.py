from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth, require_admin
from database import manager as db_manager

router = APIRouter(prefix="/api/database", tags=["database"])


def _serialize(db) -> dict:
    return {
        "id": db.id,
        "unique_id": getattr(db, "unique_id", None) or db.name,
        "name": db.name,
        "engine": db.engine,
        "connection_info": json.loads(db.connection_info),
        "created_at": db.created_at.isoformat(),
    }


@router.get("")
def list_databases(_=Depends(require_auth)):
    return [_serialize(d) for d in db_manager.list_databases()]


@router.get("/engines")
def get_database_engines(_=Depends(require_auth)):
    """Check database engines available on this host (SQLite is built-in; PostgreSQL requires host binary)."""
    pg_avail = db_manager.postgres_available()
    return {
        "engines": {
            "sqlite": True,
            "postgres": pg_avail,
        },
        "details": {
            "sqlite": {"available": True, "description": "Built-in serverless SQL database (Zero-config, recommended)"},
            "postgres": {
                "available": pg_avail,
                "description": "PostgreSQL relational server (Requires psql/createdb on host)"
            }
        }
    }


class CreateDatabaseRequest(BaseModel):
    name: str
    engine: str = "sqlite"
    auto_fallback: bool = True


@router.post("")
def create_database(req: CreateDatabaseRequest, _=Depends(require_auth)):
    try:
        return _serialize(db_manager.create_database(req.name, req.engine, auto_fallback=req.auto_fallback))
    except db_manager.DatabaseError as e:
        raise HTTPException(400, str(e))


@router.get("/{name}/status")
def status(name: str, _=Depends(require_auth)):
    try:
        return db_manager.get_status(name)
    except db_manager.DatabaseError as e:
        raise HTTPException(400, str(e))


class QueryRequest(BaseModel):
    sql: str


@router.post("/{name}/query")
def query(name: str, req: QueryRequest, _=Depends(require_admin)):
    """Admin-only — runs arbitrary SQL against a managed database. This is
    a management tool, not exposed to application-level users."""
    try:
        return db_manager.execute_query(name, req.sql)
    except db_manager.DatabaseError as e:
        raise HTTPException(400, str(e))


@router.delete("/{name}")
def delete_database(name: str, permanent: bool = False, _=Depends(require_auth)):
    try:
        db_manager.delete_database(name, permanent=permanent)
        return {"success": True, "permanent": permanent}
    except db_manager.DatabaseError as e:
        raise HTTPException(400, str(e))


@router.get("/postgres-available")
def postgres_available():
    """Unauthenticated — same honest-availability pattern as
    /api/cloudflare/available."""
    return {"postgres_available": db_manager.postgres_available()}
