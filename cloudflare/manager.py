"""
Cyan Server - Cloudflare Tunnel Manager
Wraps the real `cloudflared` CLI (spec section 9). This machine's sandboxed
network egress doesn't include Cloudflare's download domain, so this
module could not be installed/exercised live here — every function below
is genuine code against cloudflared's real command surface, but it needs
verification on a host where cloudflared can actually be installed.
Cloudflare must remain fully optional: nothing in web/, storage/, or apps/
depends on this module.
"""
from __future__ import annotations

import shutil
import subprocess

from core.database import TunnelConfig, TunnelHostname, get_session


class TunnelError(Exception):
    pass


def cloudflared_available() -> bool:
    return shutil.which("cloudflared") is not None


def login() -> str:
    """Opens the cloudflared browser-based login flow. Returns cloudflared's
    stdout (contains the auth URL) so the caller can display it."""
    if not cloudflared_available():
        raise TunnelError("cloudflared is not installed on this host")
    result = subprocess.run(["cloudflared", "tunnel", "login"],
                             capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise TunnelError(result.stderr)
    return result.stdout


def create_tunnel(name: str) -> TunnelConfig:
    if not cloudflared_available():
        raise TunnelError("cloudflared is not installed on this host")
    result = subprocess.run(["cloudflared", "tunnel", "create", name],
                             capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise TunnelError(result.stderr)

    tunnel_id = None
    for line in result.stdout.splitlines():
        if "Created tunnel" in line and "with id" in line:
            tunnel_id = line.strip().split()[-1]

    session = get_session()
    try:
        cfg = TunnelConfig(provider="cloudflare", tunnel_name=name, tunnel_id=tunnel_id, status="disabled")
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return cfg
    finally:
        session.close()


def add_hostname(tunnel_name: str, hostname: str, local_service: str) -> TunnelHostname:
    if not cloudflared_available():
        raise TunnelError("cloudflared is not installed on this host")

    result = subprocess.run(
        ["cloudflared", "tunnel", "route", "dns", tunnel_name, hostname],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise TunnelError(result.stderr)

    session = get_session()
    try:
        cfg = session.query(TunnelConfig).filter_by(tunnel_name=tunnel_name).first()
        if not cfg:
            raise TunnelError(f"Tunnel '{tunnel_name}' not found in local config")
        route = TunnelHostname(tunnel_config_id=cfg.id, hostname=hostname,
                                local_service=local_service)
        session.add(route)
        session.commit()
        session.refresh(route)
        return route
    finally:
        session.close()


def start_tunnel(tunnel_name: str) -> subprocess.Popen:
    if not cloudflared_available():
        raise TunnelError("cloudflared is not installed on this host")
    session = get_session()
    try:
        cfg = session.query(TunnelConfig).filter_by(tunnel_name=tunnel_name).first()
        if not cfg:
            raise TunnelError(f"Tunnel '{tunnel_name}' not found")
        cfg.status = "enabled"
        session.commit()
    finally:
        session.close()

    return subprocess.Popen(
        ["cloudflared", "tunnel", "run", tunnel_name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def status() -> list[dict]:
    session = get_session()
    try:
        tunnels = session.query(TunnelConfig).filter_by(provider="cloudflare").all()
        out = []
        for t in tunnels:
            hostnames = session.query(TunnelHostname).filter_by(tunnel_config_id=t.id).all()
            out.append({
                "name": t.tunnel_name, "id": t.tunnel_id, "status": t.status,
                "hostnames": [{"hostname": h.hostname, "service": h.local_service}
                              for h in hostnames],
            })
        return out
    finally:
        session.close()
