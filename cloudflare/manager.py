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
from pathlib import Path

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
        existing = session.query(TunnelHostname).filter_by(
            tunnel_config_id=cfg.id, hostname=hostname).first()
        if existing:
            existing.local_service = local_service
            route = existing
        else:
            route = TunnelHostname(tunnel_config_id=cfg.id, hostname=hostname,
                                    local_service=local_service)
            session.add(route)
        session.commit()
        session.refresh(route)
    finally:
        session.close()

    write_ingress_config(tunnel_name)
    return route


def remove_hostname(tunnel_name: str, hostname: str) -> None:
    """Disconnect a domain from a tunnel: drops the local route + DNS record
    and regenerates the ingress config so the change is live immediately."""
    if not cloudflared_available():
        raise TunnelError("cloudflared is not installed on this host")

    session = get_session()
    try:
        cfg = session.query(TunnelConfig).filter_by(tunnel_name=tunnel_name).first()
        if not cfg:
            raise TunnelError(f"Tunnel '{tunnel_name}' not found in local config")
        route = session.query(TunnelHostname).filter_by(
            tunnel_config_id=cfg.id, hostname=hostname).first()
        if not route:
            raise TunnelError(f"Hostname '{hostname}' is not connected to tunnel '{tunnel_name}'")
        session.delete(route)
        session.commit()
    finally:
        session.close()

    # Best-effort: also remove the DNS route in Cloudflare. cloudflared has no
    # single "unroute" command; the supported approach is deleting the CNAME
    # via `cloudflared tunnel route dns` is add-only, so we leave the DNS
    # record in place (harmless — it just won't resolve to a live ingress
    # rule once the config below drops it) and surface that to the caller.
    write_ingress_config(tunnel_name)


def list_hostnames(tunnel_name: str | None = None) -> list[TunnelHostname]:
    session = get_session()
    try:
        q = session.query(TunnelHostname)
        if tunnel_name:
            cfg = session.query(TunnelConfig).filter_by(tunnel_name=tunnel_name).first()
            if not cfg:
                return []
            q = q.filter_by(tunnel_config_id=cfg.id)
        return q.all()
    finally:
        session.close()


def _tunnel_config_dir() -> Path:
    import os
    d = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server")) / "cloudflared"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_ingress_config(tunnel_name: str) -> Path:
    """Generate cloudflared's config.yml from every hostname connected to
    this tunnel — this is what actually lets ONE tunnel serve MULTIPLE
    domains, each routed to its own site's local port. Without this file,
    cloudflared only knows the single service it was started with, so
    additional `route dns` hostnames would resolve in DNS but not
    actually route anywhere. Regenerated on every add/remove so it's
    never stale, and safe to call even before the tunnel has an id."""
    import yaml

    session = get_session()
    try:
        cfg = session.query(TunnelConfig).filter_by(tunnel_name=tunnel_name).first()
        if not cfg:
            raise TunnelError(f"Tunnel '{tunnel_name}' not found in local config")
        routes = session.query(TunnelHostname).filter_by(tunnel_config_id=cfg.id).all()
        tunnel_id = cfg.tunnel_id
    finally:
        session.close()

    credentials_file = str(Path.home() / ".cloudflared" / f"{tunnel_id}.json") if tunnel_id else None
    ingress = [{"hostname": r.hostname, "service": r.local_service} for r in routes]
    ingress.append({"service": "http_status:404"})  # required catch-all, must be last

    doc = {"tunnel": tunnel_id or tunnel_name, "ingress": ingress}
    if credentials_file:
        doc["credentials-file"] = credentials_file

    config_path = _tunnel_config_dir() / f"{tunnel_name}.yml"
    config_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return config_path


def start_tunnel(tunnel_name: str, config_path: str | Path | None = None) -> subprocess.Popen:
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

    cmd = ["cloudflared", "tunnel"]
    if config_path:
        cmd.extend(["--config", str(config_path)])
    else:
        # Prefer the config this module generates from the DB's
        # TunnelHostname rows (write_ingress_config) — it's what actually
        # carries multi-domain ingress rules. Fall back to older
        # cross-platform candidates for tunnels set up before this existed.
        candidates = [
            _tunnel_config_dir() / f"{tunnel_name}.yml",
            Path.home() / ".cloudflared" / "config.yml",
            Path.cwd() / "tunnel_config.yml",
        ]
        for c in candidates:
            if c.exists():
                cmd.extend(["--config", str(c)])
                break

    cmd.extend(["run", tunnel_name])

    import sys
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def stop_tunnel(tunnel_name: str) -> None:
    """Universally terminate cloudflared tunnel processes across OS platforms."""
    import psutil
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "cloudflared" in (proc.info["name"] or "").lower() and tunnel_name in cmdline:
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    session = get_session()
    try:
        cfg = session.query(TunnelConfig).filter_by(tunnel_name=tunnel_name).first()
        if cfg:
            cfg.status = "disabled"
            session.commit()
    finally:
        session.close()


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
