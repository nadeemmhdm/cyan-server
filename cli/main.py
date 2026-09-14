# Cyan Server — https://github.com/nadeemmhdm/cyan-server
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

# Windows consoles default to the legacy cp1252 code page, which can't
# encode characters like ✓ used throughout this CLI's output — caught via
# real Windows testing (UnicodeEncodeError crashing `cyan setup`).
# Reconfigure stdout/stderr to UTF-8 before anything else runs.
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

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
    import psutil
    return psutil.pid_exists(pid)


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


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Cyan Server CLI. Run without arguments to launch the interactive menu."""
    if ctx.invoked_subcommand is None:
        from cli.interactive import interactive_menu
        interactive_menu()


def _auto_token() -> str | None:
    """Auto-mint and cache an admin JWT token if running locally as the system user."""
    try:
        from security.auth import create_token
        from core.database import User, get_session
        session = get_session()
        try:
            admin = session.query(User).filter_by(role="admin").first()
            if admin:
                token = create_token(admin)
                _save_token(token)
                return token
        finally:
            session.close()
    except Exception:
        pass
    return None


def _auth_headers() -> dict:
    token = _load_token()
    if not token:
        token = _auto_token()
    if not token:
        console.print("[red]✗ Not logged in.[/red] Run: [bold]cyan login[/bold]")
        raise typer.Exit(code=1)
    return {"Authorization": f"Bearer {token}"}


def _agent_get(path: str, auth: bool = False, timeout: int = 30) -> dict:
    headers = _auth_headers() if auth else {}
    req = urllib.request.Request(f"{AGENT_BASE}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(raw)
            detail = body.get("detail", raw)
        except Exception:
            detail = raw or str(e)
        console.print(f"[red]✗ {detail}[/red]")
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
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(raw)
            detail = body.get("detail", raw)
        except Exception:
            detail = raw or str(e)
        console.print(f"[red]✗ {detail}[/red]")
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
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen([sys.executable, str(agent_path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=creationflags)
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
    import psutil
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        parent.terminate()
        parent.wait(timeout=3)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired, OSError) as e:
        pass
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


@app.command(name="version")
def version_cmd():
    """Print the current Cyan Server CLI and core version."""
    from core.version import VERSION
    console.print(f"[bold cyan]Cyan Server[/bold cyan] v[bold white]{VERSION}[/bold white]")


@app.command(name="resume")
def resume_cmd():
    """1-Click Restore: Auto-resume all sites, domains (Caddy SSL), and tunnels after restart."""
    console.print("[cyan]Running 1-Click Auto-Resume across all sites, domains, and tunnels...[/cyan]")
    result = _agent_post("/api/resume", auth=False, method="POST")
    console.print(f"[bold green]✓ Auto-Resume Completed:[/bold green] {result.get('message', 'All services active')}")
    for item in result.get("recovered_sites", []):
        console.print(f"  • Site: [bold white]{item.get('name')}[/bold white] -> {item.get('status')}")
    if result.get("caddy_reloaded"):
        console.print("  • Caddy Domains & SSL: [green]Reloaded[/green]")
    if result.get("tunnel_started"):
        console.print("  • Cloudflare Tunnel: [green]Active & Connected[/green]")


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
                port: int, domain: str = typer.Option(None),
                replicas: int = typer.Option(1, "--replicas", help="Number of load-balanced backend instances (1-8)."),
                lb_policy: str = typer.Option("round_robin", "--lb-policy",
                                               help="round_robin|least_conn|random|ip_hash (only matters when --replicas > 1)")):
    """site_type: static|node|python|php|react|docker  source_type: folder|git|docker_image"""
    result = _agent_post("/api/web", {
        "name": name, "site_type": site_type, "source_type": source_type,
        "source": source, "port": port, "domain": domain,
        "replicas": replicas, "lb_policy": lb_policy,
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


@web_app.command("files")
def web_files(name: str, path: str = typer.Argument("")):
    """List files inside a deployed site's folder."""
    result = _agent_get(f"/api/web/{name}/files?path={path}", auth=True)
    table = Table(title=f"{name}:/{path}")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Size")
    for e in result["entries"]:
        table.add_row(e["name"], "dir" if e["is_dir"] else "file",
                       "-" if e["size_bytes"] is None else f"{e['size_bytes']} B")
    console.print(table)


@web_app.command("edit")
def web_edit(name: str, path: str, content: str = typer.Option(None, help="New text content. Omit to just print the current content.")):
    """Read or write a text file within a site's folder directly — fix a
    typo without a full redeploy."""
    if content is None:
        headers = _auth_headers()
        req = urllib.request.Request(f"{AGENT_BASE}/api/web/{name}/files/download?path={path}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                console.print(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())
            console.print(f"[red]✗ {body.get('detail', str(e))}[/red]")
            raise typer.Exit(code=1)
        return
    _agent_post(f"/api/web/{name}/files/write", {"path": path, "content": content}, auth=True)
    console.print(f"[green]✓ Wrote {path}[/green]")


@web_app.command("rm-file")
def web_rm_file(name: str, path: str):
    _agent_post(f"/api/web/{name}/files?path={path}", auth=True, method="DELETE")
    console.print(f"[yellow]Deleted {path} from '{name}'[/yellow]")


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


# --- Backup / Restore -------------------------------------------------------------

backup_app = typer.Typer(help="Backup and restore the whole install (config, sites, databases).")
app.add_typer(backup_app, name="backup")


@backup_app.command("create")
def backup_create(include_storage: bool = typer.Option(False, "--include-storage", help="Also back up the storage server's files (can be large).")):
    result = _agent_post("/api/backup", {"include_storage": include_storage}, auth=True)
    console.print(f"[green]✓ Backup created: {result['filename']}[/green]")


@backup_app.command("list")
def backup_list():
    backups = _agent_get("/api/backup", auth=True)
    if not backups:
        console.print("No backups yet. Create one with: cyan backup create")
        return
    table = Table(title="Backups")
    for col in ("Filename", "Size", "Created"):
        table.add_column(col)
    for b in backups:
        size_mb = b["size_bytes"] / (1024 * 1024)
        table.add_row(b["filename"], f"{size_mb:.2f} MB", b["created_at"][:19].replace("T", " "))
    console.print(table)


@backup_app.command("config")
def backup_config(
    auto: str = typer.Option(None, help="on|off — background auto-backup"),
    retention: int = typer.Option(None, help="How many recent backups to keep"),
    interval_hours: int = typer.Option(None, help="Hours between automatic backups"),
    include_storage: str = typer.Option(None, help="on|off — include storage files in backups"),
):
    if all(v is None for v in (auto, retention, interval_hours, include_storage)):
        cfg = _agent_get("/api/backup/config", auth=True)
        console.print(cfg)
        return
    payload = {}
    if auto is not None:
        payload["auto_enabled"] = auto == "on"
    if retention is not None:
        payload["retention_count"] = retention
    if interval_hours is not None:
        payload["interval_hours"] = interval_hours
    if include_storage is not None:
        payload["include_storage"] = include_storage == "on"
    result = _agent_post("/api/backup/config", payload, auth=True)
    console.print(f"[green]✓ Backup config updated[/green]")
    console.print(result)


@backup_app.command("restore")
def backup_restore(filename: str, yes: bool = typer.Option(False, "--yes", help="Skip confirmation.")):
    """Restores a backup — this REPLACES the current database, Caddy
    config, sites, and managed databases. The agent is stopped first
    (overwriting cyan.db under a live connection doesn't take effect
    until reconnect anyway), and your current state is preserved in a
    .pre-restore-<timestamp> folder rather than deleted, in case you
    need to undo it."""
    console.print("[bold red]This will replace your current database, sites, and databases "
                   "with the contents of this backup.[/bold red]")
    console.print("Your current state will be preserved in a .pre-restore-<timestamp> folder, not deleted.")
    if not yes:
        confirm = typer.prompt("Type 'restore' to confirm")
        if confirm != "restore":
            console.print("Aborted.")
            raise typer.Exit(code=1)

    console.print("Stopping agent...")
    stop()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backup.manager import restore_backup, list_backups, BackupError

    backups = {b["filename"]: b["path"] for b in list_backups()}
    if filename not in backups:
        console.print(f"[red]✗ Backup '{filename}' not found. Run 'cyan backup list' first.[/red]")
        raise typer.Exit(code=1)

    try:
        result = restore_backup(Path(backups[filename]))
    except BackupError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]✓ Restored from {filename}[/green]")
    if result["preserved_previous_state_at"]:
        console.print(f"  Previous state preserved at: {result['preserved_previous_state_at']}")
    console.print("Starting agent (automatic recovery will bring sites/apps back up)...")
    start()


# --- Database -------------------------------------------------------------

db_app = typer.Typer(help="Manage SQL databases (SQLite always available; Postgres if installed).")
app.add_typer(db_app, name="db")


@db_app.command("list")
def db_list():
    dbs = _agent_get("/api/database", auth=True)
    if not dbs:
        console.print("No databases yet. Create one with: cyan db create <name>")
        return
    table = Table(title="Databases")
    for col in ("Name", "Engine", "Created"):
        table.add_column(col)
    for d in dbs:
        table.add_row(d["name"], d["engine"], d["created_at"][:19].replace("T", " "))
    console.print(table)


@db_app.command("create")
def db_create(name: str, engine: str = typer.Option("sqlite", help="sqlite or postgres")):
    result = _agent_post("/api/database", {"name": name, "engine": engine}, auth=True)
    console.print(f"[green]✓ Database '{result['name']}' created ({result['engine']})[/green]")
    console.print(f"  {result['connection_info']}")


@db_app.command("status")
def db_status(name: str):
    result = _agent_get(f"/api/database/{name}/status", auth=True)
    console.print(f"Engine: {result['engine']}")
    console.print(f"Size: {result['size_bytes']} bytes")
    console.print(f"Tables: {result['tables'] or '(none yet)'}")
    if "row_counts" in result and result["row_counts"]:
        for table, count in result["row_counts"].items():
            console.print(f"  {table}: {count} row(s)")


@db_app.command("query")
def db_query(name: str, sql: str):
    """Run a management SQL statement against a database. Admin only."""
    result = _agent_post(f"/api/database/{name}/query", {"sql": sql}, auth=True)
    if result.get("rows"):
        t = Table()
        for col in result["columns"]:
            t.add_column(col)
        for row in result["rows"]:
            t.add_row(*[str(row[c]) for c in result["columns"]])
        console.print(t)
    elif "rowcount" in result:
        if result["rowcount"] == -1:
            console.print("[green]OK[/green]")  # DDL (CREATE TABLE etc.) — sqlite3 doesn't report a row count for these
        else:
            console.print(f"[green]OK — {result['rowcount']} row(s) affected[/green]")
    else:
        console.print(result.get("output", result))


@db_app.command("delete")
def db_delete(name: str, permanent: bool = typer.Option(False, "--permanent", help="Skip trash (SQLite only — Postgres drops are always permanent).")):
    _agent_post(f"/api/database/{name}?permanent={'true' if permanent else 'false'}", auth=True, method="DELETE")
    console.print(f"[yellow]Database '{name}' deleted[/yellow]" +
                  ("" if permanent else " (SQLite: restorable for 30 days — cyan trash list)"))


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

tunnel_app = typer.Typer(help="Manage tunnels (Cloudflare or ngrok) for worldwide access to local sites.")
app.add_typer(tunnel_app, name="tunnel")


@tunnel_app.command("status")
def tunnel_status():
    """Shows status for both providers — whichever is installed."""
    cf_avail = _agent_get("/api/cloudflare/available")
    ngrok_avail = _agent_get("/api/ngrok/available")

    if cf_avail["cloudflared_available"]:
        result = _agent_get("/api/cloudflare/status", auth=True)
        console.print("[bold]Cloudflare:[/bold]", result["tunnels"] or "No tunnels configured.")
    else:
        console.print("[yellow]cloudflared not installed.[/yellow]")

    if ngrok_avail["ngrok_available"]:
        result = _agent_get("/api/ngrok/status", auth=True)
        console.print("[bold]ngrok:[/bold]", result["tunnels"] or "No tunnels configured.")
    else:
        console.print("[yellow]ngrok not installed.[/yellow]")

    if not cf_avail["cloudflared_available"] and not ngrok_avail["ngrok_available"]:
        console.print("\nTunnels are fully optional — LAN/web hosting works without either.")


@tunnel_app.command("create")
def tunnel_create(name: str, provider: str = typer.Option("cloudflare", help="cloudflare or ngrok")):
    if provider == "cloudflare":
        result = _agent_post("/api/cloudflare/tunnel", {"name": name}, auth=True)
        console.print(f"[green]✓ Cloudflare tunnel '{result['name']}' created[/green]")
    else:
        console.print("[yellow]ngrok tunnels are created on demand with 'cyan tunnel connect' — "
                       "there's no separate create step.[/yellow]")


@tunnel_app.command("connect")
def tunnel_connect(
    site: str,
    hostname: str = typer.Option(None, help="Domain/subdomain to route to this site. Required for Cloudflare; optional for ngrok (random URL if omitted)."),
    provider: str = typer.Option("cloudflare", help="cloudflare or ngrok"),
    tunnel_name: str = typer.Option(None, help="Cloudflare only: the tunnel to route through (from 'cyan tunnel create')."),
):
    """Connect a deployed site directly to a public tunnel — looks up the
    site's real local port automatically, so you never construct a
    local_service URL by hand. This is the actual 'local site, worldwide
    access' step: once a site has both a connected domain (cyan web
    domain) and a tunnel route to that same hostname, it's reachable from
    any device without port-forwarding or a public IP."""
    if provider == "cloudflare":
        if not hostname or not tunnel_name:
            console.print("[red]✗ Cloudflare requires both --hostname and --tunnel-name "
                           "(create one first with: cyan tunnel create <name>)[/red]")
            raise typer.Exit(code=1)
        result = _agent_post("/api/tunnel-connect/cloudflare",
                              {"site_name": site, "hostname": hostname, "tunnel_name": tunnel_name}, auth=True)
        console.print(f"[green]✓ {site} connected to https://{result['hostname']}[/green]")
    elif provider == "ngrok":
        result = _agent_post("/api/tunnel-connect/ngrok", {"site_name": site, "hostname": hostname}, auth=True)
        console.print(f"[green]✓ ngrok tunnel started for '{site}' (port {result['port']})[/green]")
        console.print("  Run 'cyan tunnel url' to get the public URL once it's up.")
    else:
        console.print(f"[red]✗ Unknown provider: {provider}[/red]")
        raise typer.Exit(code=1)


@tunnel_app.command("url")
def tunnel_url(port: int = typer.Option(None, help="Filter to a specific local port.")):
    """Get the current public ngrok URL for an active tunnel."""
    result = _agent_get(f"/api/ngrok/public-url" + (f"?port={port}" if port else ""), auth=True)
    if result["public_url"]:
        console.print(f"[green]{result['public_url']}[/green]")
    else:
        console.print("[yellow]No active ngrok tunnel found.[/yellow]")


@tunnel_app.command("domains")
def tunnel_domains(tunnel_name: str = typer.Option(None, help="Filter to one Cloudflare tunnel.")):
    """List every domain currently connected — one Cloudflare tunnel can
    carry any number of these, each pointed at its own site. Run
    'cyan tunnel connect <site> --hostname <domain> --tunnel-name <name>'
    again with a different --hostname/site to add more."""
    q = f"?tunnel_name={tunnel_name}" if tunnel_name else ""
    result = _agent_get(f"/api/cloudflare/hostnames{q}", auth=True)
    if not result:
        console.print("[yellow]No domains connected yet.[/yellow]")
        return
    table = Table()
    for col in ("Hostname", "Local service"):
        table.add_column(col)
    for r in result:
        table.add_row(r["hostname"], r["local_service"])
    console.print(table)


@tunnel_app.command("disconnect-domain")
def tunnel_disconnect_domain(hostname: str, tunnel_name: str):
    """Drop a domain from a Cloudflare tunnel's ingress config (the DNS
    CNAME itself stays in Cloudflare — cloudflared has no single-command
    way to remove that part — but traffic stops routing anywhere once
    it's out of the ingress config, and the config is regenerated
    immediately so a running tunnel picks it up on its next request)."""
    from urllib.parse import quote
    path = f"/api/cloudflare/hostname?tunnel_name={quote(tunnel_name)}&hostname={quote(hostname)}"
    _agent_post(path, auth=True, method="DELETE")
    console.print(f"[green]✓ '{hostname}' disconnected from tunnel '{tunnel_name}'[/green]")


# --- Database Management -----------------------------------------------------

db_app = typer.Typer(help="Manage SQL databases with Unique IDs.")
app.add_typer(db_app, name="db")
app.add_typer(db_app, name="database")


@db_app.command("list")
def db_list():
    """List all managed databases with their Unique IDs."""
    dbs = _agent_get("/api/database", auth=True)
    if not dbs:
        console.print("[yellow]No databases created yet.[/yellow] Run: [bold]cyan db create <name>[/bold]")
        return
    table = Table(title="Cyan Managed Databases", border_style="cyan")
    table.add_column("Unique ID", style="bold cyan")
    table.add_column("Name")
    table.add_column("Engine", style="green")
    table.add_column("Created At", style="dim")
    for d in dbs:
        uid = d.get("unique_id") or d["name"]
        table.add_row(uid, d["name"], d["engine"], d["created_at"][:19])
    console.print(table)


@db_app.command("create")
def db_create(name: str, engine: str = typer.Option("sqlite", help="sqlite or postgres")):
    """Create a new database. Automatically assigns a unique ID (name_4to6digits)."""
    res = _agent_post("/api/database", {"name": name, "engine": engine}, auth=True)
    uid = res.get("unique_id", name)
    console.print(f"[green]✓ Database '{name}' provisioned successfully![/green]")
    console.print(f"  • [bold]Unique ID:[/bold]  [cyan]{uid}[/cyan]")
    console.print(f"  • [bold]Engine:[/bold]     {res['engine']}")
    console.print(f"  • [bold]Target DB:[/bold]   {res.get('connection_info', {}).get('path', 'live')}")
    console.print(f"\nAccess externally via Client API: [bold]POST /api/v1/database/{uid}/query[/bold]")


@db_app.command("info")
def db_info(identifier: str):
    """View schema, size, and table details for a database (by unique ID or name)."""
    st = _agent_get(f"/api/database/{identifier}/status", auth=True)
    table = Table(title=f"Database Info: {identifier}", border_style="cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Engine", st.get("engine", "sqlite"))
    table.add_row("Size (bytes)", str(st.get("size_bytes", 0)))
    table.add_row("Tables", ", ".join(st.get("tables", [])) or "(no tables yet)")
    console.print(table)


@db_app.command("query")
def db_query(identifier: str, sql: str = typer.Argument(..., help="SQL query to execute")):
    """Run an arbitrary SQL query against a database (by unique ID or name)."""
    res = _agent_post(f"/api/database/{identifier}/query", {"sql": sql}, auth=True)
    rows = res.get("rows", [])
    cols = res.get("columns", [])
    if cols:
        table = Table(title=f"Query Results ({len(rows)} row{'s' if len(rows) != 1 else ''})", border_style="cyan")
        for col in cols:
            table.add_column(col)
        for r in rows:
            table.add_row(*[str(r.get(c, "")) for c in cols])
        console.print(table)
    else:
        console.print(f"[green]✓ Query executed successfully ({res.get('row_count', 0)} rows affected)[/green]")


@db_app.command("delete")
def db_delete(identifier: str, permanent: bool = typer.Option(False, "--permanent", help="Permanently delete without sending to trash")):
    """Delete a managed database (by unique ID or name)."""
    _agent_post(f"/api/database/{identifier}", None, auth=True, method="DELETE")
    console.print(f"[yellow]✓ Database '{identifier}' deleted{' (permanent)' if permanent else ''}.[/yellow]")


# --- Storage Buckets ---------------------------------------------------------

storage_app = typer.Typer(help="Manage Storage Buckets with Unique IDs.")
app.add_typer(storage_app, name="storage")
app.add_typer(storage_app, name="bucket")


@storage_app.command("list")
def storage_list():
    """List all managed storage buckets with their Unique IDs."""
    res = _agent_get("/api/storage/buckets", auth=True)
    buckets = res.get("buckets", [])
    if not buckets:
        console.print("[yellow]No storage buckets yet.[/yellow] Run: [bold]cyan storage create <name>[/bold]")
        return
    table = Table(title="Cyan Storage Buckets", border_style="cyan")
    table.add_column("Bucket ID", style="bold cyan")
    table.add_column("Name")
    table.add_column("Files", justify="right")
    table.add_column("Size (MB)", justify="right", style="green")
    table.add_column("Created", style="dim")
    for b in buckets:
        table.add_row(b["unique_id"], b["name"], str(b["file_count"]), f"{b['size_mb']:.2f}", b["created_at"][:19])
    console.print(table)


@storage_app.command("create")
def storage_create(name: str, description: str = typer.Option(None, "--desc", help="Optional description")):
    """Create a new storage bucket. Automatically assigns a unique ID (name_4to6digits)."""
    res = _agent_post("/api/storage/buckets", {"name": name, "description": description}, auth=True)
    uid = res.get("unique_id", name)
    console.print(f"[green]✓ Storage bucket '{name}' created successfully![/green]")
    console.print(f"  • [bold]Bucket ID:[/bold]    [cyan]{uid}[/cyan]")
    console.print(f"  • [bold]Description:[/bold]  {res.get('description') or 'None'}")
    console.print(f"\nUpload files via Client API: [bold]POST /api/v1/storage/{uid}/upload[/bold]")


@storage_app.command("files")
def storage_files(bucket_id: str):
    """List all files inside a storage bucket."""
    res = _agent_get(f"/api/storage/buckets/{bucket_id}/files", auth=True)
    files = res.get("files", [])
    if not files:
        console.print(f"[yellow]Bucket '{bucket_id}' is empty.[/yellow]")
        return
    table = Table(title=f"Files in Bucket: {bucket_id}", border_style="cyan")
    table.add_column("Filename", style="bold")
    table.add_column("Size (KB)", justify="right")
    table.add_column("Modified", style="dim")
    for f in files:
        table.add_row(f["name"], str(f["size_kb"]), f["modified"][:19])
    console.print(table)


@storage_app.command("upload")
def storage_upload(bucket_id: str, file_path: str):
    """Upload a file into a storage bucket."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        console.print(f"[red]✗ File '{file_path}' does not exist.[/red]")
        raise typer.Exit(code=1)

    import secrets
    import mimetypes
    boundary = "----CyanUpload" + secrets.token_hex(16)
    filename = path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_bytes = path.read_bytes()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()

    headers = _auth_headers()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    req = urllib.request.Request(f"{AGENT_BASE}/api/storage/buckets/{bucket_id}/upload", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            console.print(f"[green]✓ Uploaded '{filename}' ({len(file_bytes)} bytes) to bucket '{bucket_id}'[/green]")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        console.print(f"[red]✗ Upload failed: {err}[/red]")
        raise typer.Exit(code=1)


@storage_app.command("delete")
def storage_delete(bucket_id: str, permanent: bool = typer.Option(False, "--permanent")):
    """Delete a storage bucket."""
    _agent_post(f"/api/storage/buckets/{bucket_id}", None, auth=True, method="DELETE")
    console.print(f"[yellow]✓ Storage bucket '{bucket_id}' deleted{' (permanent)' if permanent else ''}.[/yellow]")


# --- API Key Management ------------------------------------------------------

key_app = typer.Typer(help="Manage universal API keys for external database & storage access.")
app.add_typer(key_app, name="key")
app.add_typer(key_app, name="apikey")


@key_app.command("list")
def key_list():
    """List all active API keys."""
    keys = _agent_get("/api/keys", auth=True)
    if not keys:
        console.print("[yellow]No API keys generated yet.[/yellow] Run: [bold]cyan key create <name>[/bold]")
        return
    table = Table(title="Cyan Universal API Keys", border_style="cyan")
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("API Key Token", style="cyan")
    table.add_column("Permissions", style="green")
    table.add_column("Last Used", style="dim")
    for k in keys:
        # Mask middle of key for security in terminal
        raw = k["key"]
        masked = raw[:14] + "..." + raw[-6:] if len(raw) > 20 else raw
        table.add_row(str(k["id"]), k["name"], masked, k["permissions"], (k["last_used_at"] or "Never")[:19])
    console.print(table)


@key_app.command("create")
def key_create(name: str, permissions: str = typer.Option("full", help="full|read|write")):
    """Generate a new universal API key."""
    res = _agent_post("/api/keys", {"name": name, "permissions": permissions}, auth=True)
    token = res["key"]
    console.print(f"[green]✓ Universal API Key generated successfully![/green]")
    console.print(f"  • [bold]Key Name:[/bold]     {res['name']}")
    console.print(f"  • [bold]Permissions:[/bold]  {res['permissions']}")
    console.print(f"  • [bold]API Key:[/bold]      [bold cyan]{token}[/bold cyan]")
    console.print(f"\n[yellow]Store this key securely! You can use this single key to access:[/yellow]")
    console.print(f"  1. Databases:       [bold]curl -H 'X-API-Key: {token}' http://localhost:7331/api/v1/database/<db_id>/query[/bold]")
    console.print(f"  2. Storage Buckets: [bold]curl -H 'X-API-Key: {token}' http://localhost:7331/api/v1/storage/<bucket_id>/files[/bold]")


@key_app.command("revoke")
def key_revoke(identifier: str):
    """Revoke an API key (by ID, token, or name)."""
    res = _agent_post(f"/api/keys/{identifier}", None, auth=True, method="DELETE")
    console.print(f"[yellow]✓ {res.get('message', 'API key revoked')}[/yellow]")


@app.command()
def login(username: str = typer.Option(None, "--username", "-u", help="Username"),
          password: str = typer.Option(None, "--password", "-p", help="Password")):
    """Log in to the Cyan Server Agent and save the CLI session token."""
    if not username:
        username = typer.prompt("Username", default="admin")
    if not password:
        password = typer.prompt("Password", hide_input=True)

    res = _agent_post("/api/auth/login", {"username": username, "password": password}, auth=False)
    token = res.get("access_token")
    if token:
        _save_token(token)
        console.print(f"[green]✓ Logged in successfully as '{username}'[/green]")
    else:
        console.print(f"[red]✗ Login failed[/red]")


@app.command()
def resume():
    """Universal Auto-Resume: Single-command restoration of the complete server stack.
    Restores agent daemon, hosted websites, Caddy SSL domains, and public tunnels
    after laptop restart, reboot, or system power-off."""
    from cli.interactive import run_auto_resume
    run_auto_resume()


if __name__ == "__main__":
    app()

