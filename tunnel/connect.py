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


def connect_site_to_cloudflare(site_name: str, hostname: str, tunnel_name: str) -> dict:
    from cloudflare.manager import add_hostname, TunnelError
    port = get_site_port(site_name)
    try:
        route = add_hostname(tunnel_name, hostname, f"http://localhost:{port}")
    except TunnelError as e:
        raise TunnelConnectError(str(e))
    return {"site": site_name, "hostname": route.hostname, "local_service": route.local_service}


def connect_site_to_ngrok(site_name: str, hostname: str | None = None) -> dict:
    from ngrok.manager import start_tunnel, NgrokError
    port = get_site_port(site_name)
    try:
        cfg = start_tunnel(f"site-{site_name}", port, hostname)
    except NgrokError as e:
        raise TunnelConnectError(str(e))
    return {"site": site_name, "port": port, "tunnel_name": cfg.tunnel_name}
