from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth
from tunnel.connect import connect_site_to_cloudflare, connect_site_to_ngrok, TunnelConnectError

router = APIRouter(prefix="/api/tunnel-connect", tags=["tunnel-connect"])


class ConnectCloudflareRequest(BaseModel):
    site_name: str
    hostname: str
    tunnel_name: str


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
