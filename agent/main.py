"""
Cyan Server Agent
Runs locally on the host. Exposes real system state and control endpoints
to the CLI and the Web Dashboard. No mock data — every endpoint reads
live values from core.detection / platform_impl adapters.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.detection import gather_system_report
from core.database import init_db
from core.version import VERSION
from core.update import check_for_update, apply_update, UpdateError
from platform_impl.base import get_platform_adapters
from security.auth import ensure_default_admin
from api.auth_routes import router as auth_router
from api.web_routes import router as web_router
from api.storage_routes import router as storage_router
from api.apps_routes import router as apps_router
from api.cloudflare_routes import router as cloudflare_router

app = FastAPI(title="Cyan Server Agent", version="0.2.0-phase2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Local/LAN by default. Tighten before internet exposure via Cloudflare Tunnel.
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(web_router)
app.include_router(storage_router)
app.include_router(apps_router)
app.include_router(cloudflare_router)

_START_TIME = time.time()


@app.on_event("startup")
def _startup():
    """Phase 1 <-> Phase 2 connection point: the same agent process that
    serves hardware detection (Phase 1) now also owns the DB, auth, and
    every Phase 2 module. Creates the schema and a first admin account if
    this is a fresh install."""
    init_db()
    username, generated_password = ensure_default_admin()
    if generated_password:
        print("=" * 60)
        print(f"  First run — admin account created")
        print(f"  Username: {username}")
        print(f"  Password: {generated_password}")
        print(f"  (shown once — store it now)")
        print("=" * 60)


@app.get("/api/health")
def health():
    return {"status": "ok", "uptime_seconds": round(time.time() - _START_TIME, 1), "version": VERSION}


@app.get("/api/update/check")
def update_check():
    status = check_for_update()
    return {
        "current_version": status.current_version,
        "is_git_repo": status.is_git_repo,
        "up_to_date": status.up_to_date,
        "local_commit": status.local_commit,
        "remote_commit": status.remote_commit,
        "commits_behind": status.commits_behind,
        "changelog": status.changelog,
    }


@app.post("/api/update/apply")
def update_apply():
    try:
        message = apply_update()
        return {"success": True, "message": message}
    except UpdateError as e:
        raise HTTPException(400, str(e))


@app.get("/api/system")
def system_report():
    """Full one-shot hardware/OS/network snapshot. Real data, not mocked."""
    report = gather_system_report()
    return report.to_dict()


@app.get("/api/system/live")
def system_live():
    """Lightweight, fast-changing metrics for polling (CPU%, RAM%, per-second)."""
    import psutil
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "ram_percent": vm.percent,
        "ram_used_gb": round((vm.total - vm.available) / (1024 ** 3), 2),
        "ram_total_gb": round(vm.total / (1024 ** 3), 2),
        "timestamp": time.time(),
    }


class ServiceAction(BaseModel):
    service_name: str


@app.get("/api/network/ports")
def open_ports():
    _, _, net_mgr = get_platform_adapters()
    return {"open_ports": net_mgr.list_open_ports()}


@app.get("/api/network/port-check/{port}")
def port_check(port: int):
    if not (1 <= port <= 65535):
        raise HTTPException(400, "Port must be between 1 and 65535")
    _, _, net_mgr = get_platform_adapters()
    return {"port": port, "available": net_mgr.is_port_available(port)}


@app.post("/api/services/{service_name}/start")
def service_start(service_name: str):
    _, svc_mgr, _ = get_platform_adapters()
    result = svc_mgr.start(service_name)
    if not result.success:
        raise HTTPException(500, result.stderr or "Failed to start service")
    return {"service": service_name, "action": "start", "success": True}


@app.post("/api/services/{service_name}/stop")
def service_stop(service_name: str):
    _, svc_mgr, _ = get_platform_adapters()
    result = svc_mgr.stop(service_name)
    if not result.success:
        raise HTTPException(500, result.stderr or "Failed to stop service")
    return {"service": service_name, "action": "stop", "success": True}


@app.get("/api/services/{service_name}/status")
def service_status(service_name: str):
    _, svc_mgr, _ = get_platform_adapters()
    return {"service": service_name, "status": svc_mgr.status(service_name)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7331)
