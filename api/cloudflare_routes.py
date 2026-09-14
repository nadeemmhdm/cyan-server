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


@router.get("/hostnames")
def list_hostnames(tunnel_name: str | None = None, _=Depends(require_auth)):
    """All domains currently connected — across one tunnel, or all tunnels
    if tunnel_name is omitted. This is the multi-domain view: a tunnel can
    carry any number of these, each routed to its own local service."""
    return [{"hostname": r.hostname, "local_service": r.local_service}
            for r in cf_manager.list_hostnames(tunnel_name)]


@router.delete("/hostname")
def remove_hostname(tunnel_name: str, hostname: str, _=Depends(require_auth)):
    try:
        cf_manager.remove_hostname(tunnel_name, hostname)
        return {"success": True}
    except cf_manager.TunnelError as e:
        raise HTTPException(400, str(e))


class ConnectDomainRequest(BaseModel):
    tunnel_name: str
    hostname: str
    site_name: str


@router.post("/site/connect-domain")
def connect_domain(req: ConnectDomainRequest, _=Depends(require_auth)):
    """Point a domain at a site by name — the whole point of supporting
    multiple domains per tunnel: call this once per domain you want
    pointed at (the same or different) sites, no manual local_service
    URL or DNS setup required. Regenerates the tunnel's ingress config
    (so it actually serves all connected domains, not just the last
    one) and hot-reloads a running tunnel immediately."""
    from web import manager as web_manager
    site = next((s for s in web_manager.list_sites() if s.name == req.site_name), None)
    if not site:
        raise HTTPException(404, f"Site '{req.site_name}' not found")
    local_service = f"http://localhost:{site.port}"
    try:
        route = cf_manager.add_hostname(req.tunnel_name, req.hostname, local_service)
        was_running = any(t["name"] == req.tunnel_name and t["status"] == "enabled"
                           for t in cf_manager.status())
        if was_running:
            cf_manager.stop_tunnel(req.tunnel_name)
            cf_manager.start_tunnel(req.tunnel_name)
        return {"hostname": route.hostname, "site": req.site_name, "local_service": local_service,
                "tunnel_reloaded": was_running}
    except cf_manager.TunnelError as e:
        raise HTTPException(400, str(e))


@router.post("/tunnel/{name}/start")
def start_tunnel(name: str, _=Depends(require_auth)):
    try:
        cf_manager.start_tunnel(name)
        return {"success": True}
    except cf_manager.TunnelError as e:
        raise HTTPException(400, str(e))
