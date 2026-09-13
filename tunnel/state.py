"""
Cyan Server - Tunnel & Service State Persistence (Reboot Survival)
Remembers active tunnels, connected domains, and hosted sites across system
reboots or when a laptop is powered off and turned back on.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

def _state_file() -> Path:
    d = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "tunnel_state.json"


def load_tunnel_state() -> dict:
    f = _state_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_tunnel_state(state: dict) -> None:
    f = _state_file()
    f.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_tunnel_route(tunnel_name: str, provider: str, site_name: str, hostname: str, port: int) -> None:
    """Record a connected site domain and tunnel route for persistent auto-resume."""
    state = load_tunnel_state()
    state["active_tunnel"] = tunnel_name
    state["provider"] = provider

    routes = state.get("routes", {})
    routes[site_name] = {
        "hostname": hostname,
        "port": port,
        "provider": provider,
        "tunnel_name": tunnel_name,
    }
    state["routes"] = routes
    save_tunnel_state(state)


def is_process_running(pid: int | None) -> bool:
    if not pid:
        return False
    import psutil
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def is_cloudflared_running() -> bool:
    import psutil
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            cmdline = " ".join(p.info["cmdline"] or []).lower()
            if "cloudflared" in name or "cloudflared" in cmdline:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def stop_cloudflared_tunnel() -> None:
    """Terminate any running cloudflared tunnel daemon processes."""
    import psutil
    import time
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            cmdline = " ".join(p.info["cmdline"] or []).lower()
            if "cloudflared" in name or "cloudflared" in cmdline:
                p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(0.6)


def start_cloudflared_tunnel(tunnel_name: str) -> bool:
    """Start the cloudflared tunnel in the background if not already running."""
    if is_cloudflared_running():
        return True

    cloudflared_bin = shutil.which("cloudflared")
    if not cloudflared_bin:
        candidates = [
            Path.home() / ".cyan-server" / "bin" / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared"),
            Path("C:/Program Files/cloudflared/cloudflared.exe"),
            Path("C:/ProgramData/chocolatey/bin/cloudflared.exe"),
        ]
        for c in candidates:
            if c.exists():
                cloudflared_bin = str(c)
                break

    if not cloudflared_bin:
        return False

    cfg_file = None
    for c in [
        Path.home() / ".cloudflared" / "config.yml",
        Path.cwd() / "tunnel_config.yml",
        Path.home() / ".cyan-server" / "tunnel_config.yml",
    ]:
        if c.exists():
            cfg_file = c
            break

    args = [cloudflared_bin]
    if cfg_file:
        args.extend(["tunnel", "--config", str(cfg_file), "run", tunnel_name])
    else:
        args.extend(["tunnel", "run", tunnel_name])

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    import time
    time.sleep(1.2)
    return is_cloudflared_running()


def restart_cloudflared_tunnel(tunnel_name: str) -> bool:
    """Restart cloudflared daemon to apply updated ingress configs."""
    stop_cloudflared_tunnel()
    return start_cloudflared_tunnel(tunnel_name)



def resume_all_services(agent_base: str = "http://localhost:7331") -> dict:
    """Single command execution to restore the complete Cyan Server stack:
    1. Agent Daemon (auto-starts if offline)
    2. All Websites & Apps (recover_sites, recover_apps)
    3. Caddy Reverse Proxy Domains (live SSL)
    4. Cloudflare / ngrok Public Tunnels
    """
    import time
    results = {
        "agent_running": False,
        "recovered_sites": [],
        "caddy_reloaded": False,
        "tunnel_started": False,
        "active_tunnel": None,
        "provider": None,
        "domains": [],
        "routes": [],
    }

    # 1. Check Agent status, start if offline
    try:
        with urllib.request.urlopen(f"{agent_base}/api/health", timeout=1.5) as resp:
            results["agent_running"] = resp.status == 200
    except Exception:
        results["agent_running"] = False

    if not results["agent_running"]:
        agent_script = Path(__file__).resolve().parent.parent / "agent" / "main.py"
        if agent_script.exists():
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            subprocess.Popen(
                [sys.executable, str(agent_script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            for _ in range(8):
                time.sleep(0.5)
                try:
                    with urllib.request.urlopen(f"{agent_base}/api/health", timeout=1) as resp:
                        if resp.status == 200:
                            results["agent_running"] = True
                            break
                except Exception:
                    pass

    # 2. Recover sites and apps
    try:
        from web.manager import recover_sites, list_sites
        from apps.manager import recover_apps
        from web.reverse_proxy import reload_caddy

        site_res = recover_sites()
        recover_apps()
        results["recovered_sites"] = [s["name"] for s in site_res if s.get("action") in ("recovered", "already_running")]

        # Ensure all running sites with domains are reloaded into Caddy
        sites_with_domains = [s for s in list_sites() if s.domain and s.status == "running"]
        if sites_with_domains:
            try:
                reload_caddy()
                results["caddy_reloaded"] = True
                results["domains"] = [f"{s.domain} -> :{s.port}" for s in sites_with_domains]
            except Exception:
                results["caddy_reloaded"] = False
    except Exception as e:
        results["site_error"] = str(e)

    # 3. Restore Tunnel & Public Routes
    state = load_tunnel_state()
    tunnel_name = state.get("active_tunnel")
    provider = state.get("provider", "cloudflare")
    results["provider"] = provider

    routes_dict = state.get("routes", {})
    results["routes"] = [
        {"site": s_name, "hostname": r.get("hostname"), "port": r.get("port")}
        for s_name, r in routes_dict.items()
    ]

    if provider == "cloudflare" and tunnel_name:
        results["active_tunnel"] = tunnel_name
        results["tunnel_started"] = start_cloudflared_tunnel(tunnel_name)
    elif provider == "ngrok":
        results["active_tunnel"] = tunnel_name or "ngrok"
        try:
            from ngrok.manager import start_tunnel
            for s_name, r in routes_dict.items():
                if r.get("port"):
                    start_tunnel(f"site-{s_name}", r["port"], r.get("hostname"))
            results["tunnel_started"] = True
        except Exception:
            results["tunnel_started"] = False
    elif is_cloudflared_running():
        results["tunnel_started"] = True
        results["active_tunnel"] = "running_process"

    return results
