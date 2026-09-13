"""
Cyan Server - Interactive Menu System
Provides the numbered menu interface requested for:
  [01] Host Website (Create, View Available Sites, Manage Site)
  [02] Database (List, Create with Unique ID, Query, Info, Delete)
  [03] Storage Bucket (List, Create with Unique ID, View Files, Upload, Delete)
  [04] Auto-Resume (Single-command reboot survival: restore all sites, domains & tunnels)
  [00] Exit

Includes startup update check and auto-restart capability.
"""
from __future__ import annotations

import os
import sys
import time
import json
import shutil
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()

AGENT_BASE = "http://localhost:7331"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _get_auth_headers() -> dict:
    from cli.main import _auth_headers
    return _auth_headers()


def _api_get(path: str, auth: bool = True) -> Any:
    headers = _get_auth_headers() if auth else {}
    req = urllib.request.Request(f"{AGENT_BASE}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            return {"error": json.loads(raw).get("detail", raw)}
        except Exception:
            return {"error": raw or str(e)}
    except Exception as e:
        return {"error": str(e)}


def _api_post(path: str, data: dict | None = None, auth: bool = True, method: str = "POST") -> Any:
    headers = {"Content-Type": "application/json"}
    if auth:
        headers.update(_get_auth_headers())
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(f"{AGENT_BASE}{path}", data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            return {"error": json.loads(raw).get("detail", raw)}
        except Exception:
            return {"error": raw or str(e)}
    except Exception as e:
        return {"error": str(e)}


def ensure_agent_running() -> bool:
    """Ensure the Cyan Agent daemon is running on localhost:7331. If not, auto-start it."""
    try:
        with urllib.request.urlopen(f"{AGENT_BASE}/api/health", timeout=1) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    console.print("[yellow]⚡ Cyan Agent is offline. Starting background daemon...[/yellow]")
    import subprocess
    agent_script = REPO_ROOT / "agent" / "main.py"
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    
    subprocess.Popen(
        [sys.executable, str(agent_script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    for _ in range(12):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(f"{AGENT_BASE}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    console.print("[green]✓ Cyan Agent started successfully on port 7331[/green]")
                    return True
        except Exception:
            pass

    console.print("[red]✗ Could not auto-start Cyan Agent daemon. Please run `cyan start`.[/red]")
    return False


def check_and_apply_startup_update() -> None:
    """Check for git repository updates on startup. If available, offer to update & restart."""
    try:
        from core.update import check_for_update, apply_update
        status = check_for_update()
        if not status.is_git_repo:
            return
        if not status.up_to_date and status.commits_behind > 0:
            console.print(Panel(
                f"[bold yellow]⚡ Update Available: {status.commits_behind} new commit(s) found[/bold yellow]\n"
                + "\n".join(f"  • {c}" for c in status.changelog[:4]),
                title="[cyan]System Update[/cyan]",
                border_style="yellow"
            ))
            if Confirm.ask("[bold cyan]Apply update and restart tool now?[/bold cyan]", default=True):
                console.print("[cyan]Applying updates...[/cyan]")
                msg = apply_update()
                console.print(f"[green]✓ {msg}[/green]")
                console.print("[yellow]Restarting Cyan Server CLI...[/yellow]\n")
                time.sleep(1)
                os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            console.print(f"[dim green]✓ System up to date (v{status.current_version})[/dim green]")
    except Exception:
        pass  # Gracefully proceed if offline or git not in path


def print_banner() -> None:
    from core.version import VERSION
    banner = f"""[bold cyan]
  ██████╗██╗   ██╗ █████╗ ███╗   ██╗    ███████╗███████╗██████╗ ██╗   ██╗███████╗██████╗ 
 ██╔════╝╚██╗ ██╔╝██╔══██╗████╗  ██║    ██╔════╝██╔════╝██╔══██╗██║   ██║██╔════╝██╔══██╗
 ██║      ╚████╔╝ ███████║██╔██╗ ██║    ███████╗█████╗  ██████╔╝██║   ██║█████╗  ██████╔╝
 ██║       ╚██╔╝  ██╔══██║██║╚██╗██║    ╚════██║██╔══╝  ██╔══██╗╚██╗ ██╔╝██╔══╝  ██╔══██╗
 ╚██████╗   ██║   ██║  ██║██║ ╚████║    ███████║███████╗██║  ██║ ╚████╔╝ ███████╗██║  ██║
  ╚═════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝    ╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚═╝  ╚═╝[/bold cyan]
[dim cyan]────────────────────────────────────────────────────────────────────────────────────────[/dim cyan]
  [bold white]Cyan Server[/bold white] [bold cyan]v{VERSION}[/bold cyan]  •  [green]Local Cloud & Multi-Cloud Hub[/green]  •  [link=http://localhost:7331]http://localhost:7331[/link]
[dim cyan]────────────────────────────────────────────────────────────────────────────────────────[/dim cyan]"""
    console.print(banner)


# ---------------------------------------------------------------------------
# Submenu 01: Host Website
# ---------------------------------------------------------------------------

def auto_create_default_index(target_dir: Path, site_name: str, port: int) -> Path:
    """Generate default responsive index.html starter page if not already present."""
    target_dir.mkdir(parents=True, exist_ok=True)
    index_file = target_dir / "index.html"
    if index_file.exists():
        return index_file

    template_file = REPO_ROOT / "web" / "templates" / "default_site" / "index.html"
    if template_file.exists():
        content = template_file.read_text(encoding="utf-8")
        # Replace title with site name
        content = content.replace("<title>Cyan Server — Website Deployed Successfully</title>",
                                f"<title>{site_name} — Hosted on Cyan Server</title>")
        index_file.write_text(content, encoding="utf-8")
    else:
        # Fallback modern starter page
        index_file.write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{site_name} — Hosted on Cyan Server</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    body {{ background: #070a0f; color: #f1f5f9; font-family: 'Inter', sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; text-align: center; }}
    .card {{ background: rgba(15,23,36,0.85); border: 1px solid rgba(34,211,238,0.3); border-radius: 16px; padding: 40px; max-width: 500px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
    h1 {{ color: #22d3ee; margin-bottom: 8px; }}
    p {{ color: #94a3b8; line-height: 1.6; }}
    code {{ background: #03060a; color: #38bdf8; padding: 4px 8px; border-radius: 6px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{site_name}</h1>
    <p>Your website is live and running on <code>http://localhost:{port}</code></p>
    <p>Replace this file at <code>{index_file.resolve()}</code> with your code to deploy your site.</p>
  </div>
</body>
</html>""", encoding="utf-8")

    return index_file


def get_next_available_port(start_port: int = 8080) -> int:
    """Find the next free port not registered by any existing site."""
    sites = _api_get("/api/web")
    used_ports = set()
    if isinstance(sites, list):
        for s in sites:
            if "port" in s:
                used_ports.add(int(s["port"]))

    import socket
    port = start_port
    while True:
        if port not in used_ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        port += 1


def menu_website_host() -> None:
    while True:
        console.print("\n[bold cyan]═════════════ [01] HOST WEBSITE ═════════════[/bold cyan]")
        console.print("  [bold white][1][/bold white] Create Website")
        console.print("  [bold white][2][/bold white] View Available Hosted Sites")
        console.print("  [bold white][3][/bold white] Manage Site")
        console.print("  [bold white][0][/bold white] Back to Main Menu")
        choice = Prompt.ask("\n[bold cyan]Select an option[/bold cyan]", choices=["1", "2", "3", "0", "back", "exit"], default="1")

        if choice in ("0", "back", "exit"):
            break

        elif choice == "1":
            console.print("\n[bold cyan]─── Create New Website ───[/bold cyan]")
            name = Prompt.ask("[cyan]Enter Website Name[/cyan]").strip().lower().replace(" ", "-")
            if not name:
                console.print("[red]✗ Site name cannot be empty.[/red]")
                continue

            default_dir = f"./sites/{name}"
            folder_str = Prompt.ask("[cyan]Enter Folder Path[/cyan]", default=default_dir).strip()
            folder_path = Path(folder_str).resolve()

            # Auto-assign next port
            port = get_next_available_port(8080)
            console.print(f"[dim]Auto-assigned local port:[/dim] [bold cyan]{port}[/bold cyan]")

            # Auto-create folder & default index.html starter page
            index_path = auto_create_default_index(folder_path, name, port)
            console.print(f"[green]✓ Folder ready: {folder_path}[/green]")
            console.print(f"[green]✓ Default modern web page auto-created at: {index_path.name}[/green]")

            # Register site via API
            payload = {
                "name": name,
                "site_type": "static",
                "source_type": "folder",
                "source": str(folder_path),
                "port": port,
                "domain": None,
            }
            res = _api_post("/api/web", payload)
            if "error" in res:
                console.print(f"[red]✗ Failed to register site: {res['error']}[/red]")
                continue

            console.print(f"[bold green]✓ Website '{name}' created successfully![/bold green]")
            
            # Offer immediate deployment
            if Confirm.ask("[bold cyan]Deploy website immediately now?[/bold cyan]", default=True):
                deploy_res = _api_post(f"/api/web/{name}/deploy")
                if "error" in deploy_res:
                    console.print(f"[red]✗ Deployment error: {deploy_res['error']}[/red]")
                else:
                    console.print(f"[bold green]🚀 Website is LIVE at:[/bold green] [bold cyan]http://localhost:{port}[/bold cyan]")

        elif choice == "2":
            sites = _api_get("/api/web")
            if "error" in sites:
                console.print(f"[red]✗ Error fetching sites: {sites['error']}[/red]")
                continue

            if not sites:
                console.print("[yellow]No hosted sites found. Choose option [1] to create one.[/yellow]")
                continue

            table = Table(title="Cyan Hosted Websites", border_style="cyan")
            table.add_column("Site Name", style="bold white")
            table.add_column("Type", style="cyan")
            table.add_column("Port", justify="right", style="green")
            table.add_column("Local URL", style="blue")
            table.add_column("Connected Domain", style="magenta")
            table.add_column("Status", justify="center")

            for s in sites:
                status_colored = "[green]● Running[/green]" if s.get("status") == "running" else "[yellow]○ Stopped[/yellow]"
                domain_disp = s.get("domain") or "-"
                local_url = f"http://localhost:{s.get('port')}" if s.get("status") == "running" else "-"
                table.add_row(s.get("name"), s.get("site_type"), str(s.get("port")), local_url, domain_disp, status_colored)

            console.print(table)

        elif choice == "3":
            sites = _api_get("/api/web")
            if not sites or "error" in sites:
                console.print("[yellow]No sites available to manage.[/yellow]")
                continue

            console.print("\n[bold cyan]Available Sites to Manage:[/bold cyan]")
            for idx, s in enumerate(sites, 1):
                status_icon = "🟢" if s.get("status") == "running" else "⚪"
                console.print(f"  [{idx}] {status_icon} [bold]{s.get('name')}[/bold] (Port: {s.get('port')}, Domain: {s.get('domain') or 'none'})")
            
            site_choice = Prompt.ask("\n[cyan]Select site number to manage (0 to cancel)[/cyan]", default="0")
            if not site_choice.isdigit() or int(site_choice) <= 0 or int(site_choice) > len(sites):
                continue

            chosen_site = sites[int(site_choice) - 1]
            site_name = chosen_site["name"]

            while True:
                console.print(f"\n[bold cyan]─── Manage Site: {site_name} ───[/bold cyan]")
                console.print("  [1] Deploy / Start Website")
                console.print("  [2] Stop Website")
                console.print("  [3] Connect Custom Domain (Caddy SSL Live)")
                console.print("  [4] Connect Public Tunnel (Cloudflare / ngrok)")
                console.print("  [5] View Logs")
                console.print("  [6] Delete Website")
                console.print("  [0] Back")
                action = Prompt.ask("[cyan]Choose action[/cyan]", choices=["1", "2", "3", "4", "5", "6", "0"], default="1")

                if action == "0":
                    break
                elif action == "1":
                    res = _api_post(f"/api/web/{site_name}/deploy")
                    if "error" in res:
                        console.print(f"[red]✗ {res['error']}[/red]")
                    else:
                        console.print(f"[green]✓ '{site_name}' running on port {res.get('port')}[/green]")
                elif action == "2":
                    res = _api_post(f"/api/web/{site_name}/stop")
                    console.print(f"[yellow]✓ '{site_name}' stopped[/yellow]")
                elif action == "3":
                    domain = Prompt.ask(f"[cyan]Enter domain for {site_name} (e.g. app.mydomain.com, empty to clear)[/cyan]", default="")
                    domain_val = domain.strip() or None
                    res = _api_post(f"/api/web/{site_name}/domain", {"domain": domain_val})
                    if "error" in res:
                        console.print(f"[red]✗ {res['error']}[/red]")
                    else:
                        console.print(f"[green]✓ Domain {domain_val or 'cleared'} wired to {site_name} via Caddy reverse proxy![/green]")
                elif action == "4":
                    prov = Prompt.ask("[cyan]Select Tunnel Provider[/cyan]", choices=["cloudflare", "ngrok"], default="cloudflare")
                    if prov == "cloudflare":
                        tun_name = Prompt.ask("[cyan]Enter Cloudflare Tunnel Name[/cyan]")
                        hostname = Prompt.ask("[cyan]Enter Public Hostname (e.g. site.mybrand.com)[/cyan]")
                        res = _api_post("/api/tunnels/connect", {
                            "provider": "cloudflare",
                            "site_name": site_name,
                            "tunnel_name": tun_name,
                            "hostname": hostname,
                        })
                    else:
                        hostname = Prompt.ask("[cyan]Enter Custom ngrok Hostname (optional)[/cyan]", default="")
                        res = _api_post("/api/tunnels/connect", {
                            "provider": "ngrok",
                            "site_name": site_name,
                            "hostname": hostname.strip() or None,
                        })
                    if "error" in res:
                        console.print(f"[red]✗ Tunnel connection failed: {res['error']}[/red]")
                    else:
                        console.print(f"[green]✓ Tunnel connected successfully! Route saved for auto-resume.[/green]")
                elif action == "5":
                    res = _api_get(f"/api/web/{site_name}/logs?lines=50")
                    console.print(Panel(res.get("logs") or "(no logs recorded)", title=f"Logs: {site_name}"))
                elif action == "6":
                    if Confirm.ask(f"[red]Are you sure you want to delete website '{site_name}'?[/red]", default=False):
                        _api_post(f"/api/web/{site_name}", method="DELETE")
                        console.print(f"[yellow]✓ Website '{site_name}' deleted.[/yellow]")
                        break


# ---------------------------------------------------------------------------
# Submenu 02: Database
# ---------------------------------------------------------------------------

def menu_database() -> None:
    while True:
        console.print("\n[bold cyan]═══════════════ [02] DATABASE ═══════════════[/bold cyan]")
        console.print("  [bold white][1][/bold white] List Databases (View Unique IDs & Status)")
        console.print("  [bold white][2][/bold white] Create Database (Auto-generates Unique ID: name_4to6digits)")
        console.print("  [bold white][3][/bold white] Run SQL Query / Browse Tables")
        console.print("  [bold white][4][/bold white] Database Info & Connection Details")
        console.print("  [bold white][5][/bold white] Delete Database")
        console.print("  [bold white][0][/bold white] Back to Main Menu")
        choice = Prompt.ask("\n[bold cyan]Select an option[/bold cyan]", choices=["1", "2", "3", "4", "5", "0", "back", "exit"], default="1")

        if choice in ("0", "back", "exit"):
            break

        elif choice == "1":
            dbs = _api_get("/api/database")
            if "error" in dbs:
                console.print(f"[red]✗ {dbs['error']}[/red]")
                continue
            if not dbs:
                console.print("[yellow]No managed databases created yet.[/yellow]")
                continue

            table = Table(title="Cyan Managed Databases", border_style="cyan")
            table.add_column("Unique ID", style="bold cyan")
            table.add_column("Database Name", style="white")
            table.add_column("Engine", style="green")
            table.add_column("Created", style="dim")
            for d in dbs:
                uid = d.get("unique_id") or d["name"]
                table.add_row(uid, d["name"], d["engine"], (d.get("created_at") or "")[:19])
            console.print(table)

        elif choice == "2":
            name = Prompt.ask("[cyan]Enter Database Name[/cyan]").strip()
            if not name:
                continue
            engine = Prompt.ask("[cyan]Select Engine[/cyan]", choices=["sqlite", "postgres"], default="sqlite")
            res = _api_post("/api/database", {"name": name, "engine": engine})
            if "error" in res:
                console.print(f"[red]✗ {res['error']}[/red]")
                continue

            uid = res.get("unique_id", name)
            console.print(f"[bold green]✓ Database provisioned successfully![/bold green]")
            console.print(f"  • [bold]Unique ID:[/bold]  [bold cyan]{uid}[/bold cyan]")
            console.print(f"  • [bold]Engine:[/bold]     {res.get('engine')}")
            console.print(f"  • [bold]Client API:[/bold] POST /api/v1/database/{uid}/query")

        elif choice == "3":
            ident = Prompt.ask("[cyan]Enter Database ID or Name[/cyan]").strip()
            if not ident:
                continue
            sql = Prompt.ask("[cyan]Enter SQL Query[/cyan]", default="SELECT name FROM sqlite_master WHERE type='table';")
            res = _api_post(f"/api/database/{ident}/query", {"sql": sql})
            if "error" in res:
                console.print(f"[red]✗ {res['error']}[/red]")
                continue

            rows = res.get("rows", [])
            cols = res.get("columns", [])
            if cols:
                table = Table(title=f"Query Results ({len(rows)} row{'s' if len(rows) != 1 else ''})", border_style="cyan")
                for c in cols:
                    table.add_column(c)
                for r in rows:
                    table.add_row(*[str(r.get(c, "")) for c in cols])
                console.print(table)
            else:
                console.print(f"[green]✓ Query executed successfully ({res.get('row_count', 0)} rows affected)[/green]")

        elif choice == "4":
            ident = Prompt.ask("[cyan]Enter Database ID or Name[/cyan]").strip()
            if not ident:
                continue
            st = _api_get(f"/api/database/{ident}/status")
            if "error" in st:
                console.print(f"[red]✗ {st['error']}[/red]")
                continue

            table = Table(title=f"Database Info: {ident}", border_style="cyan")
            table.add_column("Property", style="bold")
            table.add_column("Value")
            table.add_row("Engine", st.get("engine", "sqlite"))
            table.add_row("Size (bytes)", str(st.get("size_bytes", 0)))
            table.add_row("Tables", ", ".join(st.get("tables", [])) or "(no tables)")
            console.print(table)

        elif choice == "5":
            ident = Prompt.ask("[cyan]Enter Database ID or Name to delete[/cyan]").strip()
            if not ident:
                continue
            if Confirm.ask(f"[red]Are you sure you want to delete database '{ident}'?[/red]", default=False):
                res = _api_post(f"/api/database/{ident}", method="DELETE")
                if "error" in res:
                    console.print(f"[red]✗ {res['error']}[/red]")
                else:
                    console.print(f"[yellow]✓ Database '{ident}' deleted.[/yellow]")


# ---------------------------------------------------------------------------
# Submenu 03: Storage Bucket
# ---------------------------------------------------------------------------

def menu_storage_bucket() -> None:
    while True:
        console.print("\n[bold cyan]════════════ [03] STORAGE BUCKET ════════════[/bold cyan]")
        console.print("  [bold white][1][/bold white] List Storage Buckets (Unique IDs & Sizes)")
        console.print("  [bold white][2][/bold white] Create Storage Bucket (Auto-generates Unique ID: name_4to6digits)")
        console.print("  [bold white][3][/bold white] View Files in Bucket")
        console.print("  [bold white][4][/bold white] Upload File to Bucket")
        console.print("  [bold white][5][/bold white] Delete Storage Bucket")
        console.print("  [bold white][0][/bold white] Back to Main Menu")
        choice = Prompt.ask("\n[bold cyan]Select an option[/bold cyan]", choices=["1", "2", "3", "4", "5", "0", "back", "exit"], default="1")

        if choice in ("0", "back", "exit"):
            break

        elif choice == "1":
            res = _api_get("/api/storage/buckets")
            if "error" in res:
                console.print(f"[red]✗ {res['error']}[/red]")
                continue
            buckets = res.get("buckets", [])
            if not buckets:
                console.print("[yellow]No storage buckets created yet.[/yellow]")
                continue

            table = Table(title="Cyan Storage Buckets", border_style="cyan")
            table.add_column("Bucket ID", style="bold cyan")
            table.add_column("Name", style="white")
            table.add_column("Files", justify="right")
            table.add_column("Size (MB)", justify="right", style="green")
            table.add_column("Created", style="dim")
            for b in buckets:
                table.add_row(b["unique_id"], b["name"], str(b["file_count"]), f"{b['size_mb']:.2f}", b["created_at"][:19])
            console.print(table)

        elif choice == "2":
            name = Prompt.ask("[cyan]Enter Bucket Name[/cyan]").strip()
            if not name:
                continue
            desc = Prompt.ask("[cyan]Enter Description (optional)[/cyan]", default="")
            res = _api_post("/api/storage/buckets", {"name": name, "description": desc.strip() or None})
            if "error" in res:
                console.print(f"[red]✗ {res['error']}[/red]")
                continue

            uid = res.get("unique_id", name)
            console.print(f"[bold green]✓ Storage bucket created successfully![/bold green]")
            console.print(f"  • [bold]Bucket ID:[/bold]    [bold cyan]{uid}[/bold cyan]")
            console.print(f"  • [bold]Description:[/bold]  {res.get('description') or 'None'}")
            console.print(f"  • [bold]Client API:[/bold] POST /api/v1/storage/{uid}/upload")

        elif choice == "3":
            bucket_id = Prompt.ask("[cyan]Enter Bucket ID[/cyan]").strip()
            if not bucket_id:
                continue
            res = _api_get(f"/api/storage/buckets/{bucket_id}/files")
            if "error" in res:
                console.print(f"[red]✗ {res['error']}[/red]")
                continue

            files = res.get("files", [])
            if not files:
                console.print(f"[yellow]Bucket '{bucket_id}' is empty.[/yellow]")
                continue

            table = Table(title=f"Files in Bucket: {bucket_id}", border_style="cyan")
            table.add_column("Filename", style="bold white")
            table.add_column("Size (KB)", justify="right", style="green")
            table.add_column("Content Type", style="dim")
            table.add_column("Uploaded At", style="dim")
            for f in files:
                table.add_row(f["filename"], f"{f['size_bytes']/1024:.1f}", f.get("content_type", "auto"), f.get("uploaded_at", "")[:19])
            console.print(table)

        elif choice == "4":
            bucket_id = Prompt.ask("[cyan]Enter Target Bucket ID[/cyan]").strip()
            file_path_str = Prompt.ask("[cyan]Enter Local File Path to Upload[/cyan]").strip()
            fpath = Path(file_path_str)
            if not fpath.exists() or not fpath.is_file():
                console.print(f"[red]✗ File '{file_path_str}' does not exist.[/red]")
                continue

            # Upload using multipart form data
            import secrets
            import mimetypes
            boundary = "----CyanUpload" + secrets.token_hex(16)
            filename = fpath.name
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            file_bytes = fpath.read_bytes()

            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()

            headers = _get_auth_headers()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            req = urllib.request.Request(f"{AGENT_BASE}/api/storage/buckets/{bucket_id}/upload", data=body, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    console.print(f"[green]✓ Uploaded '{filename}' ({len(file_bytes)} bytes) to bucket '{bucket_id}'[/green]")
            except Exception as e:
                console.print(f"[red]✗ Upload failed: {e}[/red]")

        elif choice == "5":
            bucket_id = Prompt.ask("[cyan]Enter Bucket ID to delete[/cyan]").strip()
            if not bucket_id:
                continue
            if Confirm.ask(f"[red]Are you sure you want to delete bucket '{bucket_id}'?[/red]", default=False):
                res = _api_post(f"/api/storage/buckets/{bucket_id}", method="DELETE")
                if "error" in res:
                    console.print(f"[red]✗ {res['error']}[/red]")
                else:
                    console.print(f"[yellow]✓ Bucket '{bucket_id}' deleted.[/yellow]")


# ---------------------------------------------------------------------------
# Submenu 04: Auto-Resume (Reboot Survival)
# ---------------------------------------------------------------------------

def run_auto_resume() -> None:
    """Execute full stack restoration: daemon, websites, Caddy domains, public tunnels."""
    console.print("\n[bold cyan]════════ [04] UNIVERSAL AUTO-RESUME (REBOOT SURVIVAL) ════════[/bold cyan]")
    console.print("[dim]Restoring Agent daemon, hosted websites, Caddy SSL domains, and public tunnels...[/dim]\n")

    from tunnel.state import resume_all_services
    res = resume_all_services(AGENT_BASE)

    table = Table(title="Cyan Server Auto-Resume Status", border_style="cyan")
    table.add_column("Component", style="bold white")
    table.add_column("Status")
    table.add_column("Details", style="cyan")

    # Agent
    agent_status = "[green]● Online[/green]" if res.get("agent_running") else "[red]✗ Offline[/red]"
    table.add_row("Agent Daemon", agent_status, f"{AGENT_BASE} (Dashboard Active)")

    # Recovered Sites
    sites = res.get("recovered_sites", [])
    sites_status = f"[green]● {len(sites)} Active[/green]" if sites else "[yellow]○ None Pending[/yellow]"
    table.add_row("Hosted Websites", sites_status, ", ".join(sites) or "No stopped sites required recovery")

    # Caddy Domains
    domains = res.get("domains", [])
    caddy_status = "[green]● Reloaded[/green]" if res.get("caddy_reloaded") else "[dim]Unchanged[/dim]"
    table.add_row("Domain Reverse Proxy (Caddy)", caddy_status, ", ".join(domains) or "No custom domains attached")

    # Tunnels
    tunnel_running = res.get("tunnel_started", False)
    tunnel_status = "[green]● Running[/green]" if tunnel_running else "[yellow]○ Standby[/yellow]"
    tunnel_name = res.get("active_tunnel") or "None"
    provider = res.get("provider") or "cloudflare"
    routes = res.get("routes", [])
    routes_str = "; ".join([f"{r.get('hostname')} -> :{r.get('port')}" for r in routes]) or f"Tunnel '{tunnel_name}'"
    table.add_row(f"Public Tunnel ({provider.title()})", tunnel_status, routes_str)

    console.print(table)
    console.print("\n[bold green]✓ Universal Auto-Resume Complete![/bold green] All services restored to their pre-reboot state.")


# ---------------------------------------------------------------------------
# Main Interactive Menu Loop
# ---------------------------------------------------------------------------

def interactive_menu() -> None:
    """Entrypoint when running CLI without subcommands."""
    # 1. Print visual banner
    print_banner()

    # 2. Check for updates on startup
    check_and_apply_startup_update()

    # 3. Ensure agent daemon is alive
    ensure_agent_running()

    while True:
        console.print("\n[bold cyan]╔════════════════════════ MAIN MENU ═══════════════════════╗[/bold cyan]")
        console.print("║  [bold white][01][/bold white] 🌐  Host Website                                     ║")
        console.print("║  [bold white][02][/bold white] 🗄️   Database                                         ║")
        console.print("║  [bold white][03][/bold white] 📦  Storage Bucket                                   ║")
        console.print("║  [bold white][04][/bold white] ⚡  Auto-Resume (Restore All Sites, Domains & Tunnels)║")
        console.print("║  [bold white][00][/bold white] 🚪  Exit                                              ║")
        console.print("[bold cyan]╚══════════════════════════════════════════════════════════╝[/bold cyan]")

        choice = Prompt.ask(
            "[bold cyan]Select an option (01, 02, 03, 04, 00)[/bold cyan]",
            choices=["01", "1", "02", "2", "03", "3", "04", "4", "00", "0", "exit", "q"],
            default="01"
        )

        if choice in ("00", "0", "exit", "q"):
            console.print("\n[cyan]Thank you for using Cyan Server. Goodbye![/cyan]")
            break
        elif choice in ("01", "1"):
            menu_website_host()
        elif choice in ("02", "2"):
            menu_database()
        elif choice in ("03", "3"):
            menu_storage_bucket()
        elif choice in ("04", "4"):
            run_auto_resume()
