from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth
from cloudflare import manager as cf_manager

router = APIRouter(prefix="/api/cloudflare", tags=["cloudflare"])


@router.get("/available")
def available():
    """Unauthenticated — just reports whether cloudflared exists on this host."""
    return {"cloudflared_available": cf_manager.cloudflared_available()}


@router.get("/status")
def status(_=Depends(require_auth)):
    return {"tunnels": cf_manager.status()}


class CreateTunnelRequest(BaseModel):
    name: str


@router.post("/tunnel")
def create_tunnel(req: CreateTunnelRequest, _=Depends(require_auth)):
    try:
        cfg = cf_manager.create_tunnel(req.name)
        return {"name": cfg.tunnel_name, "id": cfg.tunnel_id, "status": cfg.status}
    except cf_manager.TunnelError as e:
        raise HTTPException(400, str(e))


class AddHostnameRequest(BaseModel):
    tunnel_name: str
    hostname: str
    local_service: str


@router.post("/hostname")
def add_hostname(req: AddHostnameRequest, _=Depends(require_auth)):
    try:
        route = cf_manager.add_hostname(req.tunnel_name, req.hostname, req.local_service)
        return {"hostname": route.hostname, "local_service": route.local_service}
    except cf_manager.TunnelError as e:
        raise HTTPException(400, str(e))


@router.post("/tunnel/{name}/start")
def start_tunnel(name: str, _=Depends(require_auth)):
    try:
        cf_manager.start_tunnel(name)
        return {"success": True}
    except cf_manager.TunnelError as e:
        raise HTTPException(400, str(e))
