# Cyan Server — https://github.com/nadeemmhdm/cyan-server
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
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
    replicas: int = 1
    lb_policy: str = "round_robin"   # round_robin | least_conn | random | ip_hash


def _serialize(site) -> dict:
    tunnel_info = {"active": False, "provider": None, "hostname": None, "tunnel_name": None}
    try:
        from tunnel.state import load_tunnel_state, is_cloudflared_running
        t_state = load_tunnel_state()
        routes = t_state.get("routes", {})
        cf_running = is_cloudflared_running()
        if site.name in routes:
            r = routes[site.name]
            provider = r.get("provider", "cloudflare")
            is_active = cf_running if provider == "cloudflare" else True
            tunnel_info = {
                "active": is_active,
                "provider": provider,
                "hostname": r.get("hostname"),
                "tunnel_name": r.get("tunnel_name"),
            }
        elif site.domain and cf_running:
            tunnel_info = {
                "active": True,
                "provider": "cloudflare",
                "hostname": site.domain,
                "tunnel_name": t_state.get("active_tunnel", "cyan-tunnel"),
            }
    except Exception:
        pass

    return {
        "id": site.id, "name": site.name, "site_type": site.site_type,
        "source_type": site.source_type, "source": site.source, "port": site.port,
        "domain": site.domain, "status": site.status, "pid": site.pid,
        "replicas": site.replicas or 1, "lb_policy": site.lb_policy or "round_robin",
        "tunnel": tunnel_info,
    }



@router.get("")
def list_sites(_=Depends(require_auth)):
    return [_serialize(s) for s in web_manager.list_sites()]


import re
import json

def _clean_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    d = re.sub(r"^https?://", "", domain.strip()).rstrip("/")
    return d or None


@router.post("")
def create_site(req: CreateSiteRequest, _=Depends(require_auth)):
    try:
        site = web_manager.create_site(
            req.name, req.site_type, req.source_type, req.source,
            req.port, _clean_domain(req.domain), req.env_vars,
            req.replicas, req.lb_policy,
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
        return _serialize(web_manager.set_domain(name, _clean_domain(req.domain)))
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.delete("/{name}")
def delete_site(name: str, permanent: bool = False, _=Depends(require_auth)):
    try:
        web_manager.delete_site(name, permanent=permanent)
        return {"success": True, "permanent": permanent}
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


# --- Site file manager -------------------------------------------------------------
# Edit a deployed site's files directly — fix a typo or swap an asset
# without a full redeploy. Same path-traversal-safe pattern as the
# storage server, scoped to one site's folder.

@router.get("/{name}/files")
def list_files(name: str, path: str = "", _=Depends(require_auth)):
    try:
        return {"path": path, "entries": web_manager.list_site_files(name, path)}
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.get("/{name}/files/download")
def download_file(name: str, path: str, _=Depends(require_auth)):
    try:
        content = web_manager.read_site_file(name, path)
        return Response(content=content, media_type="application/octet-stream")
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.post("/{name}/files/upload")
async def upload_file(name: str, path: str = Form(""), file: UploadFile = File(...), _=Depends(require_auth)):
    try:
        content = await file.read()
        target_path = f"{path.rstrip('/')}/{file.filename}" if path else file.filename
        web_manager.write_site_file(name, target_path, content)
        return {"success": True, "filename": file.filename, "size_bytes": len(content)}
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.post("/{name}/files/upload-zip")
async def upload_site_zip(name: str, path: str = Form(""), file: UploadFile = File(...), _=Depends(require_auth)):
    """Upload and automatically unpack a zip file into a site's directory."""
    try:
        content = await file.read()
        extracted = web_manager.extract_site_zip(name, content, path)
        return {"success": True, "filename": file.filename, "extracted_count": len(extracted), "files": extracted}
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.post("/{name}/files/upload-folder")
async def upload_site_folder(
    name: str,
    files: list[UploadFile] = File(...),
    paths: str = Form("[]"),
    _=Depends(require_auth)
):
    """Upload multiple files preserving relative directory structure from webkitdirectory folder picker."""
    try:
        try:
            rel_paths = json.loads(paths)
        except Exception:
            rel_paths = []

        if len(rel_paths) != len(files):
            rel_paths = [f.filename for f in files]

        clean_paths = [p.replace("\\", "/").strip("/") for p in rel_paths]

        # If all paths share a common top-level directory (e.g., 'dist/index.html'), strip it
        parts_list = [p.split("/") for p in clean_paths if p]
        if parts_list and all(len(parts) > 1 and parts[0] == parts_list[0][0] for parts in parts_list):
            clean_paths = ["/".join(parts[1:]) for parts in parts_list]

        saved = []
        for file, rel_path in zip(files, clean_paths):
            content = await file.read()
            web_manager.write_site_file(name, rel_path, content)
            saved.append(rel_path)

        return {"success": True, "files_count": len(saved), "files": saved}
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))



class WriteFileRequest(BaseModel):
    path: str
    content: str  # text content — for binary files, use the upload endpoint instead


@router.post("/{name}/files/write")
def write_file(name: str, req: WriteFileRequest, _=Depends(require_auth)):
    """Direct text edit — e.g. fixing a typo in index.html without
    re-uploading the whole file."""
    try:
        web_manager.write_site_file(name, req.path, req.content.encode("utf-8"))
        return {"success": True}
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))


@router.delete("/{name}/files")
def delete_file(name: str, path: str, _=Depends(require_auth)):
    try:
        web_manager.delete_site_file(name, path)
        return {"success": True}
    except web_manager.SiteError as e:
        raise HTTPException(400, str(e))
