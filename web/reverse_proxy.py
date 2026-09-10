"""
Cyan Server - Web Server Engine
Manages a real Caddy instance as the reverse proxy (spec section 14).
Generates a Caddyfile from the Website table and reloads Caddy via its
admin API — no manual config editing required from the user.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from core.database import Website

DATA_DIR = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CADDYFILE_PATH = DATA_DIR / "Caddyfile"
CADDY_ADMIN_URL = "http://localhost:2019"
DASHBOARD_PORT = int(os.environ.get("CYAN_DASHBOARD_PORT", 7331))


class CaddyNotAvailable(RuntimeError):
    pass


def caddy_binary() -> str:
    path = shutil.which("caddy")
    if not path:
        raise CaddyNotAvailable(
            "caddy is not installed. Install it via the PackageManager "
            "abstraction (plan_install('caddy')) before enabling web hosting."
        )
    return path


def render_caddyfile(sites: list[Website]) -> str:
    """Build a Caddyfile from live DB rows. No manual editing needed."""
    blocks = []
    for site in sites:
        if site.status != "running":
            continue
        host = site.domain if site.domain else f":{_pick_public_port(site)}"
        blocks.append(
            f"{host} {{\n"
            f"    reverse_proxy localhost:{site.port}\n"
            f"    log {{\n"
            f"        output file {DATA_DIR}/logs/{site.name}.log\n"
            f"    }}\n"
            f"}}\n"
        )
    if not blocks:
        # Minimal valid Caddyfile with just the admin API + a placeholder.
        return "# Cyan Server managed Caddyfile — no active sites\n"
    return "\n".join(blocks)


def _pick_public_port(site: Website) -> int:
    """Sites without a domain get exposed on 8000 + their DB id, so
    multiple no-domain sites don't collide on the same Caddy listener."""
    return 8000 + site.id


def write_caddyfile(sites: list[Website]) -> Path:
    (DATA_DIR / "logs").mkdir(exist_ok=True)
    content = render_caddyfile(sites)
    CADDYFILE_PATH.write_text(content)
    return CADDYFILE_PATH


def is_caddy_running() -> bool:
    try:
        r = httpx.get(f"{CADDY_ADMIN_URL}/config/", timeout=1.5)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def start_caddy() -> subprocess.Popen:
    """Start Caddy in the background using our managed Caddyfile."""
    binary = caddy_binary()
    write_caddyfile([])  # ensure file exists before first start
    log_path = DATA_DIR / "caddy.log"
    log_file = open(log_path, "a")
    proc = subprocess.Popen(
        [binary, "run", "--config", str(CADDYFILE_PATH), "--adapter", "caddyfile"],
        stdout=log_file, stderr=subprocess.STDOUT,
    )
    for _ in range(20):
        if is_caddy_running():
            break
        time.sleep(0.25)
    return proc


def reload_caddy(sites: list[Website]) -> bool:
    """Regenerate the Caddyfile from current DB state and hot-reload Caddy
    via its admin API (no downtime, no manual restart)."""
    write_caddyfile(sites)
    if not is_caddy_running():
        start_caddy()
        return True
    binary = caddy_binary()
    result = subprocess.run(
        [binary, "reload", "--config", str(CADDYFILE_PATH), "--adapter", "caddyfile"],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0
