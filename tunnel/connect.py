# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Cyan Server - Site-to-Tunnel Connection
The piece that actually makes "deploy locally, access worldwide" a single
command instead of three: looks up a deployed site's real local port and
wires it straight to a tunnel hostname, without the caller ever having to
construct a `local_service` URL by hand.

This is provider-agnostic — works the same way whether the tunnel is
Cloudflare or ngrok, and is where a site's connected domain (from
web/manager.py::set_domain) and its public tunnel access meet: once a
site has both a domain (for Caddy's routing) and a tunnel route pointing
at that same domain, the site is reachable from any device, anywhere,
without port-forwarding or a public IP.
"""
from __future__ import annotations

from web.manager import list_sites, SiteError


class TunnelConnectError(Exception):
    pass


def get_site_port(site_name: str) -> int:
    for site in list_sites():
        if site.name == site_name:
            return site.port
    raise TunnelConnectError(f"Site '{site_name}' not found — check `cyan web list`")


import re
from pathlib import Path


def get_default_tunnel_name() -> str:
    candidates = [
        Path.cwd() / "tunnel_config.yml",
        Path.home() / ".cloudflared" / "config.yml",
        Path.home() / ".cyan-server" / "tunnel_config.yml"
    ]
    for c in candidates:
        if c.exists():
            try:
                for line in c.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("tunnel:"):
                        val = line.split(":", 1)[1].strip()
                        if val:
                            return val
            except Exception:
                pass
    return "cyan-tunnel"


def connect_site_to_cloudflare(site_name: str, hostname: str, tunnel_name: str | None = None) -> dict:
    from cloudflare.manager import add_hostname, TunnelError, cloudflared_available
    from tunnel.state import record_tunnel_route, restart_cloudflared_tunnel
    import web.manager as web_manager

    if not cloudflared_available():
        raise TunnelConnectError("cloudflared is not installed on this host")

    default_name = get_default_tunnel_name()
    if not tunnel_name or (tunnel_name.endswith("-tunnel") and tunnel_name != default_name and default_name == "cyan-tunnel"):
        tunnel_name = default_name

    clean_host = re.sub(r"^https?://", "", hostname.strip()).rstrip("/")
    port = get_site_port(site_name)

    # Automatically set domain on the site if not already set, reloading Caddy
    try:
        site = web_manager.get_site(site_name)
        if site and (not site.domain or site.domain != clean_host):
            web_manager.set_domain(site_name, clean_host)
    except Exception:
        pass

    # Add hostname route to cloudflared, and regenerate the full multi-domain
    # ingress config from every hostname on this tunnel (add_hostname() does
    # this internally via cloudflare.manager.write_ingress_config — the
    # single source of truth for this file; previously a second, separate
    # writer here duplicated the job with the site's real port hardcoded to
    # 80, and only touched a config file that already happened to exist).
    try:
        add_hostname(tunnel_name, clean_host, f"http://127.0.0.1:{port}")
    except TunnelError as e:
        if "not installed" in str(e).lower() or "not found" in str(e).lower():
            raise TunnelConnectError(str(e))
        pass

    # Persist state for reboot recovery
    record_tunnel_route(tunnel_name=tunnel_name, provider="cloudflare", site_name=site_name, hostname=clean_host, port=port)

    # Actively launch or refresh the background cloudflared daemon
    tunnel_started = restart_cloudflared_tunnel(tunnel_name)

    return {
        "site": site_name,
        "hostname": clean_host,
        "local_service": f"http://127.0.0.1:{port}",
        "tunnel_started": tunnel_started,
        "status": "connected" if tunnel_started else "route_saved"
    }


def disconnect_site_tunnel(site_name: str) -> dict:
    """Disconnect and clean up public tunnel route for a site."""
    from tunnel.state import load_tunnel_state, save_tunnel_state, stop_cloudflared_tunnel
    state = load_tunnel_state()
    routes = state.get("routes", {})
    if site_name in routes:
        route_info = routes.pop(site_name)
        state["routes"] = routes
        save_tunnel_state(state)
        # If no more cloudflare routes are active, cleanly stop the daemon
        has_other_cf = any(r.get("provider") == "cloudflare" for r in routes.values())
        if not has_other_cf:
            try:
                stop_cloudflared_tunnel()
            except Exception:
                pass
        return {"disconnected": True, "site": site_name, "removed_route": route_info}
    return {"disconnected": False, "site": site_name, "message": "No active tunnel route for this site"}


def connect_site_to_ngrok(site_name: str, hostname: str | None = None) -> dict:
    from ngrok.manager import start_tunnel, NgrokError
    from tunnel.state import record_tunnel_route
    port = get_site_port(site_name)
    clean_host = re.sub(r"^https?://", "", hostname.strip()).rstrip("/") if hostname else None
    try:
        cfg = start_tunnel(f"site-{site_name}", port, clean_host)
        record_tunnel_route(tunnel_name=f"site-{site_name}", provider="ngrok", site_name=site_name, hostname=clean_host or "ngrok-dynamic", port=port)
    except NgrokError as e:
        raise TunnelConnectError(str(e))
    return {"site": site_name, "port": port, "tunnel_name": cfg.tunnel_name}


