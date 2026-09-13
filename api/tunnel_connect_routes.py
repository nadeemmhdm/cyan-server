from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth
from tunnel.connect import connect_site_to_cloudflare, connect_site_to_ngrok, TunnelConnectError

router = APIRouter(prefix="/api/tunnel-connect", tags=["tunnel-connect"])


class ConnectCloudflareRequest(BaseModel):
    site_name: str
    hostname: str
    tunnel_name: str | None = None


@router.get("/default-config")
def get_tunnel_default_config(_=Depends(require_auth)):
    from tunnel.connect import get_default_tunnel_name
    from tunnel.state import is_cloudflared_running, load_tunnel_state
    state = load_tunnel_state()
    return {
        "default_tunnel_name": get_default_tunnel_name(),
        "active_tunnel": state.get("active_tunnel") or get_default_tunnel_name(),
        "is_running": is_cloudflared_running(),
    }


@router.post("/cloudflare")
def connect_cloudflare(req: ConnectCloudflareRequest, _=Depends(require_auth)):
    try:
        return connect_site_to_cloudflare(req.site_name, req.hostname, req.tunnel_name)
    except TunnelConnectError as e:
        raise HTTPException(400, str(e))


class ConnectNgrokRequest(BaseModel):
    site_name: str
    hostname: str | None = None


@router.post("/ngrok")
def connect_ngrok(req: ConnectNgrokRequest, _=Depends(require_auth)):
    try:
        return connect_site_to_ngrok(req.site_name, req.hostname)
    except TunnelConnectError as e:
        raise HTTPException(400, str(e))


@router.post("/{site_name}/disconnect")
def disconnect_tunnel(site_name: str, _=Depends(require_auth)):
    try:
        from tunnel.connect import disconnect_site_tunnel
        return disconnect_site_tunnel(site_name)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/{site_name}/start")
def start_tunnel(site_name: str, _=Depends(require_auth)):
    try:
        from tunnel.state import load_tunnel_state, start_cloudflared_tunnel
        state = load_tunnel_state()
        tunnel_name = state.get("active_tunnel", "cyan-tunnel")
        started = start_cloudflared_tunnel(tunnel_name)
        return {"started": started, "site": site_name, "tunnel_name": tunnel_name}
    except Exception as e:
        raise HTTPException(400, str(e))

