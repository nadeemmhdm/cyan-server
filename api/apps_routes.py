from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth
from apps import manager as apps_manager

router = APIRouter(prefix="/api/apps", tags=["apps"])


class InstallAppRequest(BaseModel):
    manifest_yaml: str


def _serialize(app) -> dict:
    return {
        "id": app.id, "name": app.name, "app_type": app.app_type,
        "status": app.status, "container_id": app.container_id,
    }


@router.get("")
def list_apps(_=Depends(require_auth)):
    return [_serialize(a) for a in apps_manager.list_apps()]


@router.post("")
def install_app(req: InstallAppRequest, _=Depends(require_auth)):
    try:
        app = apps_manager.install_app(req.manifest_yaml)
        return _serialize(app)
    except apps_manager.RequirementError as e:
        raise HTTPException(409, str(e))
    except apps_manager.AppError as e:
        raise HTTPException(400, str(e))


@router.post("/{name}/start")
def start_app(name: str, _=Depends(require_auth)):
    try:
        return _serialize(apps_manager.start_app(name))
    except apps_manager.AppError as e:
        raise HTTPException(400, str(e))


@router.post("/{name}/stop")
def stop_app(name: str, _=Depends(require_auth)):
    try:
        return _serialize(apps_manager.stop_app(name))
    except apps_manager.AppError as e:
        raise HTTPException(400, str(e))
