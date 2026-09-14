# Cyan Server — https://github.com/nadeemmhdm/cyan-server
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth
from ngrok import manager as ngrok_manager

router = APIRouter(prefix="/api/ngrok", tags=["ngrok"])


@router.get("/available")
def available():
    """Unauthenticated — same honest-availability pattern as /api/cloudflare/available."""
    return {"ngrok_available": ngrok_manager.ngrok_available()}


@router.get("/status")
def status(_=Depends(require_auth)):
    return {"tunnels": ngrok_manager.status()}


class StartTunnelRequest(BaseModel):
    name: str
    port: int
    hostname: str | None = None


@router.post("/tunnel")
def start_tunnel(req: StartTunnelRequest, _=Depends(require_auth)):
    try:
        cfg = ngrok_manager.start_tunnel(req.name, req.port, req.hostname)
        return {"name": cfg.tunnel_name, "status": cfg.status}
    except ngrok_manager.NgrokError as e:
        raise HTTPException(400, str(e))


@router.get("/public-url")
def public_url(port: int | None = None, _=Depends(require_auth)):
    try:
        url = ngrok_manager.get_public_url(port)
        return {"public_url": url}
    except ngrok_manager.NgrokError as e:
        raise HTTPException(400, str(e))


@router.post("/tunnel/{name}/stop")
def stop_tunnel(name: str, _=Depends(require_auth)):
    try:
        ngrok_manager.stop_tunnel(name)
        return {"success": True}
    except ngrok_manager.NgrokError as e:
        raise HTTPException(400, str(e))
