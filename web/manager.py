"""
Cyan Server - Web Server: Site Manager
Handles: create -> select source (folder/git/docker) -> pick port -> deploy
-> configure reverse proxy -> running website. Every step here does real
work against the filesystem/process table/Docker/Caddy — nothing here is
a placeholder button.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import Website, DeploymentEvent, get_session
from platform_impl.base import get_platform_adapters
from web.reverse_proxy import reload_caddy

DATA_DIR = Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))
SITES_DIR = DATA_DIR / "sites"
SITES_DIR.mkdir(parents=True, exist_ok=True)


class SiteError(Exception):
    pass


def _site_dir(name: str) -> Path:
    d = SITES_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_event(session, website_id: int, action: str, success: bool, message: str):
    session.add(DeploymentEvent(website_id=website_id, action=action,
                                 success=success, message=message))
    session.commit()


def create_site(name: str, site_type: str, source_type: str, source: str,
                 port: int, domain: str | None = None,
                 env_vars: dict | None = None) -> Website:
    session = get_session()
    try:
        if session.query(Website).filter_by(name=name).first():
            raise SiteError(f"Site '{name}' already exists")

        _, _, net_mgr = get_platform_adapters()
        if not net_mgr.is_port_available(port):
            raise SiteError(f"Port {port} is already in use")

        site = Website(
            name=name, site_type=site_type, source_type=source_type,
            source=source, port=port, domain=domain,
            env_vars=json.dumps(env_vars or {}), status="stopped",
        )
        session.add(site)
        session.commit()
        session.refresh(site)
        _log_event(session, site.id, "create", True, "Site record created")
        return site
    finally:
        session.close()


def fetch_source(site: Website) -> Path:
    """Populate the site's working directory from folder/git/docker source."""
    target = _site_dir(site.name)

    if site.source_type == "folder":
        src = Path(site.source)
        if not src.exists():
            raise SiteError(f"Source folder does not exist: {src}")
        if src.resolve() != target.resolve():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        return target

    if site.source_type == "git":
        import git
        if target.exists() and any(target.iterdir()):
            shutil.rmtree(target)
            target.mkdir()
        try:
            git.Repo.clone_from(site.source, target, depth=1)
        except git.GitCommandError as e:
            raise SiteError(f"git clone failed: {e}")
        return target

    if site.source_type == "docker_image":
        return target  # nothing to fetch — docker pulls at run time

    raise SiteError(f"Unknown source_type: {site.source_type}")


def _start_command(site: Website, path: Path) -> list[str] | None:
    """Return the process command for non-docker site types. Static sites
    are served with Python's http.server — a real, working static server,
    not a placeholder."""
    if site.site_type == "static":
        return [sys.executable, "-m", "http.server", str(site.port), "--directory", str(path)]

    if site.site_type == "node":
        if not shutil.which("node"):
            raise SiteError("node is not installed on this host")
        package_json = path / "package.json"
        if package_json.exists():
            subprocess.run(["npm", "install", "--omit=dev"], cwd=path,
                            capture_output=True, text=True, timeout=300)
        return ["node", "server.js"]

    if site.site_type == "python":
        req = path / "requirements.txt"
        if req.exists():
            subprocess.run([sys.executable, "-m", "pip", "install",
                             "--break-system-packages", "-r", str(req)],
                            capture_output=True, text=True, timeout=300)
        main = path / "main.py"
        if not main.exists():
            raise SiteError("python site requires a main.py entrypoint")
        return [sys.executable, str(main)]

    return None


def deploy_site(name: str) -> Website:
    session = get_session()
    try:
        site = session.query(Website).filter_by(name=name).first()
        if not site:
            raise SiteError(f"Site '{name}' not found")

        try:
            path = fetch_source(site)
        except SiteError as e:
            _log_event(session, site.id, "deploy", False, str(e))
            raise

        env = os.environ.copy()
        env.update(json.loads(site.env_vars or "{}"))
        env["PORT"] = str(site.port)

        if site.site_type == "docker":
            if not shutil.which("docker"):
                _log_event(session, site.id, "deploy", False, "Docker not installed")
                raise SiteError("Docker is not installed on this host")
            cmd = ["docker", "run", "-d", "--name", f"cyan-{name}",
                   "-p", f"{site.port}:{site.port}", site.source]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                _log_event(session, site.id, "deploy", False, result.stderr)
                raise SiteError(f"docker run failed: {result.stderr}")
            site.status = "running"
            site.pid = None
        else:
            cmd = _start_command(site, path)
            if cmd is None:
                raise SiteError(f"Unsupported site_type: {site.site_type}")
            log_path = path / "cyan.log"
            with open(log_path, "a") as logf:
                proc = subprocess.Popen(cmd, cwd=path, env=env,
                                         stdout=logf, stderr=subprocess.STDOUT)
            site.pid = proc.pid
            site.status = "running"

        session.commit()
        _log_event(session, site.id, "deploy", True, f"Deployed as {site.site_type} on port {site.port}")

        all_sites = session.query(Website).all()
        reload_caddy(all_sites)
        session.refresh(site)
        return site
    finally:
        session.close()


def stop_site(name: str) -> Website:
    session = get_session()
    try:
        site = session.query(Website).filter_by(name=name).first()
        if not site:
            raise SiteError(f"Site '{name}' not found")

        if site.site_type == "docker":
            subprocess.run(["docker", "stop", f"cyan-{name}"], capture_output=True, timeout=30)
            subprocess.run(["docker", "rm", f"cyan-{name}"], capture_output=True, timeout=30)
        elif site.pid:
            try:
                os.kill(site.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        site.status = "stopped"
        site.pid = None
        session.commit()
        _log_event(session, site.id, "stop", True, "Site stopped")

        all_sites = session.query(Website).all()
        reload_caddy(all_sites)
        session.refresh(site)
        return site
    finally:
        session.close()


def list_sites() -> list[Website]:
    session = get_session()
    try:
        return session.query(Website).all()
    finally:
        session.close()


def get_site_logs(name: str, lines: int = 100) -> str:
    session = get_session()
    try:
        site = session.query(Website).filter_by(name=name).first()
        if not site:
            raise SiteError(f"Site '{name}' not found")
    finally:
        session.close()

    if site.site_type == "docker":
        result = subprocess.run(["docker", "logs", "--tail", str(lines), f"cyan-{name}"],
                                 capture_output=True, text=True, timeout=15)
        return result.stdout + result.stderr

    log_path = _site_dir(name) / "cyan.log"
    if not log_path.exists():
        return ""
    return "\n".join(log_path.read_text().splitlines()[-lines:])
