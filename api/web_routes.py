from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from security.dependencies import require_auth
from web import manager as web_manager

router = APIRouter(prefix="/api/web", tags=["web"])


class CreateSiteRequest(BaseModel):
    name: str
    site_type: str          # static | node | python | docker
    source_type: str        # folder | git | docker_image
    source: str
    port: int
    domain: str | None = None
    env_vars: dict = {}


def _serialize(site) -> dict:
    return {
        "id": site.id, "name": site.name, "site_type": site.site_type,
        "source_type": site.source_type, "source": site.source, "port": site.port,
        "domain": site.domain, "status": site.status, "pid": site.pid,
    }


@router.get("")
def list_sites(_=Depends(require_auth)):
    return [_serialize(s) for s in web_manager.list_sites()]


@router.post("")
def create_site(req: CreateSiteRequest, _=Depends(require_auth)):
    try:
        site = web_manager.create_site(
            req.name, req.site_type, req.source_type, req.source,
            req.port, req.domain, req.env_vars,
        )
        return _serialize(site)
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.post("/{name}/deploy")
def deploy_site(name: str, _=Depends(require_auth)):
    try:
        site = web_manager.deploy_site(name)
        return _serialize(site)
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.post("/{name}/stop")
def stop_site(name: str, _=Depends(require_auth)):
    try:
        site = web_manager.stop_site(name)
        return _serialize(site)
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.get("/{name}/logs")
def site_logs(name: str, lines: int = 100, _=Depends(require_auth)):
    try:
        return {"logs": web_manager.get_site_logs(name, lines)}
    except web_manager.SiteError as e:
        raise HTTPException(404, str(e))


class SetDomainRequest(BaseModel):
    domain: str | None = None  # None clears it


@router.post("/{name}/domain")
def set_domain(name: str, req: SetDomainRequest, _=Depends(require_auth)):
    try:
        return _serialize(web_manager.set_domain(name, req.domain))
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.delete("/{name}")
def delete_site(name: str, permanent: bool = False, _=Depends(require_auth)):
    try:
        web_manager.delete_site(name, permanent=permanent)
        return {"success": True, "permanent": permanent}
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))
