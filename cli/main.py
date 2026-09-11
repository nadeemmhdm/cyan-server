"""
Cyan Server CLI
Talks to the local Agent over HTTP (http://localhost:7331). Every command
below reflects real agent state — nothing here is simulated output.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="cyan", help="Cyan Server — turn this device into a server.")
console = Console()

AGENT_BASE = "http://localhost:7331"
TOKEN_PATH = Path.home() / ".cyan-server" / ".cyan_cli_token"
PIDFILE_PATH = Path.home() / ".cyan-server" / "agent.pid"


def _write_pidfile(pid: int) -> None:
    PIDFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE_PATH.write_text(str(pid))


def _read_pidfile() -> int | None:
    if not PIDFILE_PATH.exists():
        return None
    try:
        return int(PIDFILE_PATH.read_text().strip())
    except ValueError:
        return None


def _process_alive(pid: int) -> bool:
    import os as _os
    try:
        _os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _load_token() -> str | None:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    return None


def _save_token(token: str) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token)
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass


def _auth_headers() -> dict:
    token = _load_token()
    if not token:
        console.print("[red]✗ Not logged in.[/red] Run: [bold]cyan login[/bold]")
        raise typer.Exit(code=1)
    return {"Authorization": f"Bearer {token}"}


def _agent_get(path: str, auth: bool = False) -> dict:
    headers = _auth_headers() if auth else {}
    req = urllib.request.Request(f"{AGENT_BASE}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
        console.print(f"[red]✗ {body.get('detail', str(e))}[/red]")
        raise typer.Exit(code=1)
    except (urllib.error.URLError, ConnectionRefusedError):
        console.print("[red]✗ Cannot reach Cyan Agent.[/red] "
                       "Is it running? Try: [bold]cyan start[/bold]")
        raise typer.Exit(code=1)


def _agent_post(path: str, payload: dict | None = None, auth: bool = False, method: str = "POST") -> dict:
    headers = {"Content-Type": "application/json"}
    if auth:
        headers.update(_auth_headers())
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(f"{AGENT_BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
        console.print(f"[red]✗ {body.get('detail', str(e))}[/red]")
        raise typer.Exit(code=1)
    except (urllib.error.URLError, ConnectionRefusedError):
        console.print("[red]✗ Cannot reach Cyan Agent.[/red]")
        raise typer.Exit(code=1)


@app.command()
def status():
    """Show live agent + system status."""
    health = _agent_get("/api/health")
    live = _agent_get("/api/system/live")

    table = Table(title="Cyan Server Status")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Agent", "[green]running[/green]")
    table.add_row("Agent uptime", f"{health['uptime_seconds']:.0f}s")
    table.add_row("CPU", f"{live['cpu_percent']:.1f}%")
    table.add_row("RAM", f"{live['ram_used_gb']:.1f} / {live['ram_total_gb']:.1f} GB "
                          f"({live['ram_percent']:.1f}%)")
    console.print(table)


@app.command()
def setup():
    """Run automatic hardware/OS detection and show a configuration summary."""
    from core.detection import gather_system_report

    console.print("[bold]Detecting operating system...[/bold]")
    report = gather_system_report()
    console.print(f"  ✓ {report.os_name} ({report.os_version})")

    console.print("[bold]Detecting architecture...[/bold]")
    console.print(f"  ✓ {report.architecture}")

    console.print("[bold]Detecting CPU...[/bold]")
    console.print(f"  ✓ {report.cpu_model} "
                   f"({report.cpu_cores_physical} physical / {report.cpu_cores_logical} logical)")

    console.print("[bold]Detecting RAM...[/bold]")
    console.print(f"  ✓ {report.ram_total_gb} GB total, {report.ram_available_gb} GB available")

    console.print("[bold]Detecting storage...[/bold]")
    for disk in report.disks:
        console.print(f"  ✓ {disk.mountpoint}: {disk.free_gb} GB free of {disk.total_gb} GB")

    console.print("[bold]Detecting network...[/bold]")
    for iface in report.network_interfaces:
        if iface.address and iface.is_up:
            console.print(f"  ✓ {iface.name}: {iface.address}")
    console.print(f"  Primary IP: {report.primary_ip or 'unknown'}")

    console.print("[bold]Checking dependencies...[/bold]")
    docker_status = "[green]available[/green]" if report.docker_available else "[yellow]not found[/yellow]"
    console.print(f"  Docker: {docker_status}"
                   + (f" ({report.docker_version})" if report.docker_version else ""))

    console.print(f"\n[bold]Resource profile:[/bold] {report.resource_profile}")
    console.print("\n[green]Detection complete.[/green] "
                   "Run [bold]cyan web[/bold] / [bold]cyan storage[/bold] to configure services.")


@app.command()
def start():
    """Start the Cyan Server agent (API + dashboard, one process)."""
    import subprocess
    existing_pid = _read_pidfile()
    if existing_pid and _process_alive(existing_pid):
        console.print(f"[yellow]Agent already running (pid {existing_pid})[/yellow]")
        return
    agent_path = Path(__file__).resolve().parent.parent / "agent" / "main.py"
    console.print("Starting Cyan Agent...")
    proc = subprocess.Popen([sys.executable, str(agent_path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        try:
            urllib.request.urlopen(f"{AGENT_BASE}/api/health", timeout=1)
            console.print(f"[green]✓ Agent running at {AGENT_BASE}[/green]")
            return
        except (urllib.error.URLError, ConnectionRefusedError):
            time.sleep(0.5)
    console.print("[red]✗ Agent did not start in time. Check logs.[/red]")


@app.command()
def stop():
    """Stop the running Cyan Server agent."""
    pid = _read_pidfile()
    if not pid or not _process_alive(pid):
        console.print("[yellow]No running agent found (pidfile missing or stale).[/yellow]")
        return
    import signal
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as e:
        console.print(f"[red]✗ Could not stop agent (pid {pid}): {e}[/red]")
        return
    for _ in range(10):
        if not _process_alive(pid):
            console.print(f"[green]✓ Agent stopped (was pid {pid})[/green]")
            return
        time.sleep(0.3)
    console.print(f"[yellow]Sent stop signal to pid {pid}, but it's still shutting down.[/yellow]")


@app.command()
def restart():
    """Restart the agent in one command. Automatic recovery (see `cyan up`)
    means anything that was running comes back up as part of this."""
    console.print("Restarting Cyan Server...")
    stop()
    time.sleep(1)
    start()


@app.command()
def update(apply: bool = typer.Option(False, "--apply", help="Actually apply the update, not just check."),
           auto: str = typer.Option(None, "--auto", help="on|off — enable/disable automatic background checks + apply.")):
    """Check for (and optionally apply) updates via git — spec's `cyan update`."""
    if auto is not None:
        if auto not in ("on", "off"):
            console.print("[red]--auto must be 'on' or 'off'[/red]")
            raise typer.Exit(code=1)
        enabled = auto == "on"
        _agent_post("/api/update/config", {"auto_check": True, "auto_apply": enabled}, auth=False)
        console.print(f"[green]✓ Auto-update {'enabled' if enabled else 'disabled'}[/green] "
                       f"(background checks stay on either way; this controls whether updates auto-apply)")
        return

    result = _agent_get("/api/update/check")
    if not result["is_git_repo"]:
        console.print("[yellow]Not a git checkout — cannot self-update. Reinstall via the installer.[/yellow]")
        return
    if result["up_to_date"]:
        console.print(f"[green]✓ Up to date[/green] (v{result['current_version']}, {result['local_commit'] or '?'})")
        return

    if result.get("is_security_update"):
        console.print(f"[bold red]{result['commits_behind']} update(s) available — includes a SECURITY fix:[/bold red]")
    else:
        console.print(f"[yellow]{result['commits_behind']} update(s) available:[/yellow]")
    for line in result["changelog"]:
        console.print(f"  {line}")

    if result.get("is_security_update"):
        console.print("[red]Security updates apply automatically in the background "
                       "regardless of your --auto setting.[/red]")

    if not apply:
        console.print("\nRun [bold]cyan update --apply[/bold] to install.")
        return

    applied = _agent_post("/api/update/apply", auth=False, method="POST")
    console.print(f"[green]✓ {applied['message']}[/green]")


@app.command()
def up():
    """Bring everything back up in one command — recovers any website or
    application that was running before the agent last stopped (e.g.
    after a reboot or time offline). Safe to run any time; already-running
    services are left alone."""
    result = _agent_post("/api/recover", auth=False, method="POST")
    all_results = result["sites"] + result["applications"]
    if not all_results:
        console.print("[green]Nothing to recover — no services were previously running.[/green]")
        return
    for r in all_results:
        if r["action"] == "recovered":
            console.print(f"[green]✓ {r['name']}: recovered[/green]")
        elif r["action"] == "already_running":
            console.print(f"  {r['name']}: already running")
        else:
            console.print(f"[red]✗ {r['name']}: {r.get('error', 'failed')}[/red]")


@app.command()
def uninstall(yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt.")):
    """Remove Cyan Server: stops the agent, deletes the install directory
    and all local data (database, storage, secrets). Deployed sites/apps
    on the host (Docker containers, Caddy config) are also torn down.
    Asks for confirmation unless --yes is passed."""
    data_dir = Path.home() / ".cyan-server"
    install_dir = Path(__file__).resolve().parent.parent

    console.print("[bold red]This will:[/bold red]")
    console.print(f"  • Stop the Cyan Server agent")
    console.print(f"  • Stop every deployed website and application")
    console.print(f"  • Delete {data_dir} (database, storage, secrets, logs)")
    console.print(f"  • Delete {install_dir} (the Cyan Server code itself)")
    console.print("[bold]This cannot be undone.[/bold]")

    if not yes:
        confirm = typer.prompt("Type 'uninstall' to confirm")
        if confirm != "uninstall":
            console.print("Aborted — nothing was removed.")
            raise typer.Exit(code=1)

    # Best-effort teardown of running services before deleting anything.
    try:
        if _load_token():
            for site in _agent_get("/api/web", auth=True):
                if site["status"] == "running":
                    try:
                        _agent_post(f"/api/web/{site['name']}/stop", auth=True)
                    except Exception:
                        pass
            for a in _agent_get("/api/apps", auth=True):
                if a["status"] == "running":
                    try:
                        _agent_post(f"/api/apps/{a['name']}/stop", auth=True)
                    except Exception:
                        pass
    except Exception:
        pass  # agent may already be down — don't block the uninstall on this

    stop()

    import shutil
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
        console.print(f"[green]✓ Removed {data_dir}[/green]")

    console.print(f"\n[green]✓ Cyan Server stopped and data removed.[/green]")
    console.print(f"To finish, delete the install directory yourself: [bold]rm -rf {install_dir}[/bold]")
    console.print("(not done automatically, since that's the directory this command is running from)")


@app.command()
def health():
    """Agent health check."""
    result = _agent_get("/api/health")
    console.print(result)


@app.command()
def ports():
    """List currently open/listening ports on this host."""
    result = _agent_get("/api/network/ports")
    console.print(f"Open ports: {result['open_ports']}")


def _prompt_password() -> str:
    """hide_input=True depends on the terminal supporting echo control,
    which fails (and previously crashed the whole login with an Abort) on
    some terminals/SSH sessions/Windows consoles. Fall back to a visible
    prompt rather than dying — a visible local password prompt beats a
    broken login."""
    try:
        return typer.prompt("Password", hide_input=True)
    except Exception:
        console.print("[yellow]Couldn't hide input on this terminal — password will be visible as you type.[/yellow]")
        return typer.prompt("Password", hide_input=False)


@app.command()
def login(password: str = typer.Option(None, help="If omitted, you'll be prompted (username is always 'admin' for now).")):
    """Log in to the local agent (http://localhost:7331) and cache a session token."""
    username = "admin"
    if password is None:
        password = _prompt_password()
    result = _agent_post("/api/auth/login", {"username": username, "password": password})
    _save_token(result["access_token"])
    console.print(f"[green]✓ Logged in as {username} ({result['role']})[/green]")


# --- Web hosting -------------------------------------------------------------

web_app = typer.Typer(help="Manage hosted websites.")
app.add_typer(web_app, name="web")


@web_app.command("list")
def web_list():
    sites = _agent_get("/api/web", auth=True)
    if not sites:
        console.print("No sites yet. Create one with: cyan web create")
        return
    table = Table(title="Websites")
    for col in ("Name", "Type", "Port", "Domain", "Status"):
        table.add_column(col)
    for s in sites:
        table.add_row(s["name"], s["site_type"], str(s["port"]), s["domain"] or "-", s["status"])
    console.print(table)


@web_app.command("create")
def web_create(name: str, site_type: str, source_type: str, source: str,
                port: int, domain: str = typer.Option(None)):
    """site_type: static|node|python|docker  source_type: folder|git|docker_image"""
    result = _agent_post("/api/web", {
        "name": name, "site_type": site_type, "source_type": source_type,
        "source": source, "port": port, "domain": domain,
    }, auth=True)
    console.print(f"[green]✓ Site '{result['name']}' created (stopped)[/green]. "
                   f"Run [bold]cyan web deploy {name}[/bold] to start it.")


@web_app.command("deploy")
def web_deploy(name: str):
    result = _agent_post(f"/api/web/{name}/deploy", auth=True)
    console.print(f"[green]✓ '{name}' running on port {result['port']}[/green]")


@web_app.command("stop")
def web_stop(name: str):
    _agent_post(f"/api/web/{name}/stop", auth=True)
    console.print(f"[yellow]'{name}' stopped[/yellow]")


@web_app.command("logs")
def web_logs(name: str, lines: int = 50):
    result = _agent_get(f"/api/web/{name}/logs?lines={lines}", auth=True)
    console.print(result["logs"] or "(no logs yet)")


@web_app.command("domain")
def web_domain(name: str, domain: str = typer.Argument(None, help="Domain or subdomain, e.g. example.com or api.example.com. Omit to clear.")):
    """Connect a domain or subdomain to a site — Caddy reloads live, no redeploy needed."""
    result = _agent_post(f"/api/web/{name}/domain", {"domain": domain}, auth=True)
    if domain:
        console.print(f"[green]✓ {name} is now connected to {domain}[/green]")
    else:
        console.print(f"[yellow]Domain cleared for {name}[/yellow]")


@web_app.command("delete")
def web_delete(name: str, permanent: bool = typer.Option(False, "--permanent", help="Skip trash, delete immediately.")):
    _agent_post(f"/api/web/{name}?permanent={'true' if permanent else 'false'}", auth=True, method="DELETE")
    if permanent:
        console.print(f"[yellow]Permanently deleted '{name}'[/yellow]")
    else:
        console.print(f"[green]✓ '{name}' moved to trash[/green] (restorable for 30 days — cyan trash list)")


# --- Storage -------------------------------------------------------------

storage_app = typer.Typer(help="Manage the storage server.")
app.add_typer(storage_app, name="storage")


@storage_app.command("list")
def storage_list(path: str = ""):
    result = _agent_get(f"/api/storage/list?path={path}", auth=True)
    table = Table(title=f"/{path}")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Size")
    for e in result["entries"]:
        table.add_row(e["name"], "dir" if e["is_dir"] else "file",
                       "-" if e["size_bytes"] is None else f"{e['size_bytes']} B")
    console.print(table)


@storage_app.command("usage")
def storage_usage():
    result = _agent_get("/api/storage/usage", auth=True)
    quota = f"{result['quota_gb']} GB" if result["quota_gb"] else "unlimited"
    console.print(f"Used: {result['used_gb']} GB / {quota}")


@storage_app.command("mkdir")
def storage_mkdir(path: str):
    _agent_post("/api/storage/mkdir", {"path": path}, auth=True)
    console.print(f"[green]✓ Created {path}[/green]")


@storage_app.command("share")
def storage_share(path: str, expires_hours: float = 24):
    result = _agent_post("/api/storage/share", {"path": path, "expires_hours": expires_hours}, auth=True)
    console.print(f"Share token: {result['token']}")
    console.print(f"URL: {AGENT_BASE}/api/storage/share/{result['token']}")


@storage_app.command("delete")
def storage_delete(path: str, permanent: bool = typer.Option(False, "--permanent", help="Skip trash, delete immediately.")):
    _agent_post(f"/api/storage/item?path={path}" + ("&permanent=true" if permanent else ""),
                auth=True, method="DELETE")
    if permanent:
        console.print(f"[yellow]Permanently deleted {path}[/yellow]")
    else:
        console.print(f"[green]✓ Moved {path} to trash[/green] (restorable for 30 days — cyan trash list)")


# --- Trash / Recycle Bin -------------------------------------------------------------

trash_app = typer.Typer(help="Recover or permanently remove deleted items (30-day retention).")
app.add_typer(trash_app, name="trash")


@trash_app.command("list")
def trash_list():
    items = _agent_get("/api/trash", auth=True)
    if not items:
        console.print("Trash is empty.")
        return
    table = Table(title="Trash")
    for col in ("ID", "Type", "Name", "Deleted", "Expires"):
        table.add_column(col)
    for i in items:
        table.add_row(str(i["id"]), i["item_type"], i["name"],
                       i["deleted_at"][:19].replace("T", " "),
                       i["expires_at"][:19].replace("T", " "))
    console.print(table)


@trash_app.command("restore")
def trash_restore_cmd(trash_id: int):
    result = _agent_post(f"/api/trash/{trash_id}/restore", auth=True)
    console.print(f"[green]✓ Restored to {result['restored_to']}[/green]")


@trash_app.command("empty")
def trash_empty(yes: bool = typer.Option(False, "--yes", help="Skip confirmation.")):
    if not yes:
        confirm = typer.prompt("Type 'empty' to permanently delete everything in trash")
        if confirm != "empty":
            console.print("Aborted.")
            raise typer.Exit(code=1)
    result = _agent_post("/api/trash/empty", auth=True)
    console.print(f"[green]✓ Permanently deleted {len(result['deleted'])} item(s)[/green]")


# --- Applications -------------------------------------------------------------

apps_app = typer.Typer(help="Manage installed applications.")
app.add_typer(apps_app, name="apps")


@apps_app.command("list")
def apps_list():
    result = _agent_get("/api/apps", auth=True)
    if not result:
        console.print("No applications installed.")
        return
    table = Table(title="Applications")
    for col in ("Name", "Type", "Status"):
        table.add_column(col)
    for a in result:
        table.add_row(a["name"], a["app_type"], a["status"])
    console.print(table)


@apps_app.command("install")
def apps_install(manifest_path: str):
    """Install an application from a YAML manifest file (see spec section 8)."""
    manifest_yaml = Path(manifest_path).read_text()
    result = _agent_post("/api/apps", {"manifest_yaml": manifest_yaml}, auth=True)
    console.print(f"[green]✓ Installed '{result['name']}'[/green]. "
                   f"Run [bold]cyan apps start {result['name']}[/bold] to launch it.")


@apps_app.command("start")
def apps_start(name: str):
    _agent_post(f"/api/apps/{name}/start", auth=True)
    console.print(f"[green]✓ '{name}' started[/green]")


@apps_app.command("stop")
def apps_stop(name: str):
    _agent_post(f"/api/apps/{name}/stop", auth=True)
    console.print(f"[yellow]'{name}' stopped[/yellow]")


# --- Cloudflare Tunnel -------------------------------------------------------------

tunnel_app = typer.Typer(help="Manage Cloudflare Tunnel (optional, requires cloudflared).")
app.add_typer(tunnel_app, name="tunnel")


@tunnel_app.command("status")
def tunnel_status():
    avail = _agent_get("/api/cloudflare/available")
    if not avail["cloudflared_available"]:
        console.print("[yellow]cloudflared is not installed on this host.[/yellow] "
                       "Cloudflare Tunnel is fully optional — LAN/web hosting works without it.")
        return
    result = _agent_get("/api/cloudflare/status", auth=True)
    console.print(result["tunnels"] or "No tunnels configured.")


@tunnel_app.command("create")
def tunnel_create(name: str):
    result = _agent_post("/api/cloudflare/tunnel", {"name": name}, auth=True)
    console.print(f"[green]✓ Tunnel '{result['name']}' created[/green]")


if __name__ == "__main__":
    app()
