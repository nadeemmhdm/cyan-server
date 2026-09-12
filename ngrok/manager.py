"""
Cyan Server - ngrok Tunnel Manager
Second tunnel provider alongside Cloudflare (spec section 9 says "more
tunnel service" support), for the case where someone doesn't have a
Cloudflare account/domain but wants instant public access to a local
site. Real code against ngrok's actual CLI and its local status API
(http://127.0.0.1:4040/api/tunnels) — could not be installed/exercised in
this build sandbox because ngrok's own binary download (via `npm install
-g ngrok`, which fetches from bin.equinox.io at postinstall time) isn't
reachable from here. Same honesty tier as the Postgres and PHP adapters:
real code, needs verification on a host with real network access.

ngrok must remain fully optional, same as Cloudflare — nothing in web/,
storage/, apps/, or database/ depends on this module.
"""
from __future__ import annotations

import shutil
import subprocess
import time

import httpx

from core.database import TunnelConfig, get_session

NGROK_LOCAL_API = "http://127.0.0.1:4040/api/tunnels"


class NgrokError(Exception):
    pass


def ngrok_available() -> bool:
    return shutil.which("ngrok") is not None


def set_authtoken(token: str) -> None:
    if not ngrok_available():
        raise NgrokError("ngrok is not installed on this host")
    result = subprocess.run(["ngrok", "config", "add-authtoken", token],
                             capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise NgrokError(result.stderr)


def start_tunnel(name: str, port: int, hostname: str | None = None) -> TunnelConfig:
    """Starts `ngrok http <port>` in the background. hostname is only
    honored on paid ngrok plans (custom/reserved domains) — on the free
    tier ngrok assigns a random public URL, retrievable via get_public_url()
    once the tunnel is up."""
    if not ngrok_available():
        raise NgrokError("ngrok is not installed on this host")

    cmd = ["ngrok", "http", str(port), "--log=stdout"]
    if hostname:
        cmd.append(f"--domain={hostname}")

    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Give ngrok a moment to bring up its local API before the caller
    # asks get_public_url() what happened.
    for _ in range(20):
        try:
            httpx.get(NGROK_LOCAL_API, timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.25)

    session = get_session()
    try:
        cfg = TunnelConfig(provider="ngrok", tunnel_name=name, status="enabled")
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return cfg
    finally:
        session.close()


def get_public_url(port: int | None = None) -> str | None:
    """Queries ngrok's local status API for the public URL of an active
    tunnel. If port is given, returns the URL for that specific tunnel;
    otherwise returns the first active one."""
    try:
        resp = httpx.get(NGROK_LOCAL_API, timeout=3)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise NgrokError(f"ngrok local API not reachable — is a tunnel running? ({e})")

    tunnels = resp.json().get("tunnels", [])
    for t in tunnels:
        if port is None or str(port) in t.get("config", {}).get("addr", ""):
            return t.get("public_url")
    return None


def stop_tunnel(name: str) -> None:
    if not ngrok_available():
        raise NgrokError("ngrok is not installed on this host")
    subprocess.run(["pkill", "-f", "ngrok http"], capture_output=True, timeout=10)

    session = get_session()
    try:
        cfg = session.query(TunnelConfig).filter_by(provider="ngrok", tunnel_name=name).first()
        if cfg:
            cfg.status = "disabled"
            session.commit()
    finally:
        session.close()


def status() -> list[dict]:
    session = get_session()
    try:
        rows = session.query(TunnelConfig).filter_by(provider="ngrok").all()
        return [{"name": r.tunnel_name, "status": r.status} for r in rows]
    finally:
        session.close()
