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

CADDY_ADMIN_URL = "http://localhost:2019"
DASHBOARD_PORT = int(os.environ.get("CYAN_DASHBOARD_PORT", 7331))


def _data_dir() -> Path:
    """Re-read CYAN_DATA_DIR on every call rather than caching it at
    import time — a cached path goes stale if CYAN_DATA_DIR changes
    within a process (e.g. multiple test files sharing one pytest
    process); caught via real Windows testing."""
    d = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _caddyfile_path() -> Path:
    return _data_dir() / "Caddyfile"


class CaddyNotAvailable(RuntimeError):
    pass


def caddy_binary() -> str:
    path = shutil.which("caddy")
    if not path:
        raise CaddyNotAvailable(
            "caddy is not installed. Install it via the PackageManager "
            "abstraction (plan_install('caddy')) before enabling web hosting. "
            "On Windows: winget install CaddyServer.Caddy"
        )
    return path


def _errors_dir() -> Path:
    return Path(__file__).resolve().parent / "templates" / "errors"


def render_caddyfile(sites: list[Website]) -> str:
    """Build a Caddyfile from live DB rows. No manual editing needed."""
    data_dir = _data_dir()
    errors_dir = _errors_dir()

    # Global options block must come first, before any site block.
    # skip_install_trust stops Caddy from trying to install a local root CA
    # into the OS trust store on Windows. auto_https disable_redirects allows
    # Caddy to listen on HTTP (port 80) behind Cloudflare Tunnel without
    # forcing an infinite redirect loop.
    global_opts = (
        "{\n"
        "    skip_install_trust\n"
        "    auto_https disable_redirects\n"
        "}\n\n"
    )

    blocks = []
    for site in sites:
        if site.status != "running":
            continue
        host = f"http://{site.domain}, {site.domain}" if site.domain else f":{_pick_public_port(site)}"
        blocks.append(
            f"{host} {{\n"
            f"    reverse_proxy localhost:{site.port} {{\n"
            f"        @custom status 403 404 500 502 503\n"
            f"        handle_response @custom {{\n"
            f'            root * "{errors_dir.as_posix()}"\n'
            f"            try_files /{{rp.status_code}}.html /error.html\n"
            f"            file_server {{\n"
            f"                status {{rp.status_code}}\n"
            f"            }}\n"
            f"        }}\n"
            f"    }}\n"
            f"    handle_errors {{\n"
            f'        root * "{errors_dir.as_posix()}"\n'
            f"        try_files /{{err.status_code}}.html /error.html\n"
            f"        file_server {{\n"
            f"            status {{err.status_code}}\n"
            f"        }}\n"
            f"    }}\n"
            f"    log {{\n"
            f'        output file "{data_dir.as_posix()}/logs/{site.name}.log"\n'
            f"    }}\n"
            f"}}\n"
        )
    if not blocks:
        return global_opts + "# Cyan Server managed Caddyfile — no active sites\n"
    return global_opts + "\n".join(blocks)


def _pick_public_port(site: Website) -> int:
    """Sites without a domain get exposed on 8000 + their DB id, so
    multiple no-domain sites don't collide on the same Caddy listener."""
    return 8000 + site.id


def write_caddyfile(sites: list[Website]) -> Path:
    (_data_dir() / "logs").mkdir(exist_ok=True)
    content = render_caddyfile(sites)
    path = _caddyfile_path()
    path.write_text(content)
    return path


def is_caddy_running() -> bool:
    try:
        r = httpx.get(f"{CADDY_ADMIN_URL}/config/", timeout=1.5)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def start_caddy(sites: list[Website] | None = None) -> subprocess.Popen:
    """Start Caddy in the background using our managed Caddyfile.

    Takes the currently-active sites so it can write the REAL config on
    first start. Previously this always wrote an empty config first
    (write_caddyfile([])) — harmless if Caddy had never run before, but
    if reload_caddy() had already written the actual sites into the
    Caddyfile moments earlier (e.g. Caddy crashed and this is a restart),
    calling start_caddy() would silently wipe that real config back to
    empty right before launching. Caught via real Windows testing. Now
    this only writes a blank placeholder if no Caddyfile exists yet at
    all — otherwise it starts Caddy with whatever's already on disk, or
    with the sites passed in if you have them.
    """
    binary = caddy_binary()
    if sites is not None:
        write_caddyfile(sites)
    elif not _caddyfile_path().exists():
        write_caddyfile([])
    log_path = _data_dir() / "caddy.log"
    log_file = open(log_path, "a")
    proc = subprocess.Popen(
        [binary, "run", "--config", str(_caddyfile_path()), "--adapter", "caddyfile"],
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
        start_caddy(sites)
        return True
    binary = caddy_binary()
    result = subprocess.run(
        [binary, "reload", "--config", str(_caddyfile_path()), "--adapter", "caddyfile"],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0
