# Cyan Server — https://github.com/nadeemmhdm/cyan-server
from __future__ import annotations

import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth
from core.database import ApiKey, User, get_session

router = APIRouter(prefix="/api/keys", tags=["apikeys"])


def _serialize_key(key: ApiKey) -> dict:
    return {
        "id": key.id,
        "key": key.key,
        "name": key.name,
        "permissions": key.permissions,
        "created_at": key.created_at.isoformat(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }


class CreateApiKeyRequest(BaseModel):
    name: str
    permissions: str = "full"


@router.get("")
def list_api_keys(payload: dict = Depends(require_auth)):
    session = get_session()
    try:
        user = session.query(User).filter_by(username=payload.get("sub")).first()
        user_id = user.id if user else None
        keys = session.query(ApiKey).filter((ApiKey.user_id == user_id) | (ApiKey.user_id.is_(None))).all()
        return [_serialize_key(k) for k in keys]
    finally:
        session.close()


@router.post("")
def create_api_key(req: CreateApiKeyRequest, payload: dict = Depends(require_auth)):
    if not req.name.strip():
        raise HTTPException(400, "API key name cannot be blank")

    raw_token = "cyan_live_" + secrets.token_hex(20)
    session = get_session()
    try:
        user = session.query(User).filter_by(username=payload.get("sub")).first()
        key_obj = ApiKey(
            key=raw_token,
            name=req.name.strip(),
            user_id=user.id if user else None,
            permissions=req.permissions,
        )
        session.add(key_obj)
        session.commit()
        session.refresh(key_obj)
        return _serialize_key(key_obj)
    finally:
        session.close()


@router.delete("/{identifier}")
def revoke_api_key(identifier: str, _=Depends(require_auth)):
    session = get_session()
    try:
        key_obj = None
        if identifier.isdigit():
            key_obj = session.query(ApiKey).filter_by(id=int(identifier)).first()
        if not key_obj:
            key_obj = session.query(ApiKey).filter((ApiKey.key == identifier) | (ApiKey.name == identifier)).first()

        if not key_obj:
            raise HTTPException(404, f"API key '{identifier}' not found")

        session.delete(key_obj)
        session.commit()
        return {"success": True, "message": f"API key '{key_obj.name}' revoked"}
    finally:
        session.close()
