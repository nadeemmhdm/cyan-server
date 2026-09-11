"""
Cyan Server Agent
Runs locally on the host. Exposes real system state and control endpoints
to the CLI and the Web Dashboard. No mock data — every endpoint reads
live values from core.detection / platform_impl adapters.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.detection import gather_system_report
from core.database import init_db
from core.version import VERSION
from core.update import (check_for_update, apply_update, UpdateError,
                          get_update_config, set_update_config, start_auto_update_thread)
from security.headers import SecurityHeadersMiddleware
from web.manager import recover_sites
from apps.manager import recover_apps
from platform_impl.base import get_platform_adapters
from security.auth import ensure_default_admin
from api.auth_routes import router as auth_router
from api.web_routes import router as web_router
from api.storage_routes import router as storage_router
from api.apps_routes import router as apps_router
from api.cloudflare_routes import router as cloudflare_router
from api.trash_routes import router as trash_router

app = FastAPI(title="Cyan Server Agent", version="0.3.2")

app.add_middleware(SecurityHeadersMiddleware)

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
app.include_router(trash_router)

_START_TIME = time.time()


@app.on_event("startup")
def _startup():
    """The same agent process that serves hardware detection also owns
    the DB, auth, and every service module (web/storage/apps/cloudflare).
    Creates the schema and a first admin account if this is a fresh
    install."""
    pidfile = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server")) / "agent.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(os.getpid()))

    init_db()
    # Custom admin credentials at first-run setup time, if provided —
    # otherwise a random password is generated and shown once, as before.
    username, generated_password = ensure_default_admin(
        username=os.environ.get("CYAN_ADMIN_USER", "admin"),
        password=os.environ.get("CYAN_ADMIN_PASSWORD"),
    )
    if generated_password:
        print("=" * 60)
        print(f"  First run — admin account created")
        print(f"  Username: {username}")
        print(f"  Password: {generated_password}")
        print(f"  (shown once — store it now)")
        print("=" * 60)

    # Automatic Recovery (spec section 20): bring back anything that was
    # marked running before this agent process last stopped.
    site_results = recover_sites()
    app_results = recover_apps()
    recovered = [r for r in site_results + app_results if r["action"] == "recovered"]
    if recovered:
        print(f"Recovered {len(recovered)} service(s) that were running before restart: "
              f"{[r['name'] for r in recovered]}")

    # Auto-update background thread (off by auto-apply default, on by auto-check default)
    app.state.update_stop_event = start_auto_update_thread()

    from trash.manager import start_auto_purge_thread
    app.state.trash_stop_event = start_auto_purge_thread()


@app.on_event("shutdown")
def _shutdown():
    pidfile = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server")) / "agent.pid"
    try:
        if pidfile.exists() and pidfile.read_text().strip() == str(os.getpid()):
            pidfile.unlink()
    except OSError:
        pass


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


@app.get("/api/update/config")
def update_config_get():
    cfg = get_update_config()
    return {
        "auto_check": cfg.auto_check, "auto_apply": cfg.auto_apply,
        "check_interval_minutes": cfg.check_interval_minutes,
        "last_checked_at": cfg.last_checked_at.isoformat() if cfg.last_checked_at else None,
        "last_check_result": cfg.last_check_result,
    }


class UpdateConfigRequest(BaseModel):
    auto_check: bool | None = None
    auto_apply: bool | None = None
    check_interval_minutes: int | None = None


@app.post("/api/update/config")
def update_config_set(req: UpdateConfigRequest):
    cfg = set_update_config(req.auto_check, req.auto_apply, req.check_interval_minutes)
    return {"auto_check": cfg.auto_check, "auto_apply": cfg.auto_apply,
            "check_interval_minutes": cfg.check_interval_minutes}


@app.post("/api/recover")
def recover_all():
    """The 'single command brings everything back up' endpoint — same
    logic the agent runs automatically on startup, exposed so it can also
    be triggered on demand (``cyan up``) without restarting the agent."""
    sites = recover_sites()
    applications = recover_apps()
    return {"sites": sites, "applications": applications}


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


# --- Dashboard ---------------------------------------------------------------
# Served from this same process/port so `python3 agent/main.py` (or
# `cyan start`) is the one command that brings up both the API and the
# dashboard — no separate static file server needed. Mounted last so it
# never shadows the /api/* routes above.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="dashboard")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7331)
