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

def _data_dir() -> Path:
    """Re-reads CYAN_DATA_DIR on every call rather than caching it at
    import time. A stale cached path is a real bug: if CYAN_DATA_DIR
    changes within a process (e.g. multiple test files sharing one pytest
    process), a module that cached the old value keeps writing there —
    caught during real Windows testing (tests/test_web_trash.py failing
    because this module still had the directory from an earlier test)."""
    return Path(os.environ.get("CYAN_DATA_DIR", Path.home() / ".cyan-server"))


def get_sites_dir() -> Path:
    d = _data_dir() / "sites"
    d.mkdir(parents=True, exist_ok=True)
    return d


class SiteError(Exception):
    pass


def _site_dir(name: str) -> Path:
    d = get_sites_dir() / name
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

        if source_type == "folder":
            src = Path(source)
            src.mkdir(parents=True, exist_ok=True)
            index_file = src / "index.html"
            # If the folder has no index.html and no other code files, add the modern starter template
            if not index_file.exists() and not any(f for f in src.iterdir() if f.name != "cyan.log"):
                default_template = Path(__file__).resolve().parent / "templates" / "default_site" / "index.html"
                if default_template.exists():
                    shutil.copy(default_template, index_file)

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
    default_template = Path(__file__).resolve().parent / "templates" / "default_site" / "index.html"

    if site.source_type == "folder":
        src = Path(site.source)
        src.mkdir(parents=True, exist_ok=True)
        index_file = src / "index.html"
        if not index_file.exists() and not any(f for f in src.iterdir() if f.name != "cyan.log"):
            if default_template.exists():
                shutil.copy(default_template, index_file)

        if src.resolve() != target.resolve():
            # Sync target with src: remove files from target that were deleted in src (preserve cyan.log)
            if target.exists():
                for item in list(target.iterdir()):
                    if item.name == "cyan.log":
                        continue
                    if not (src / item.name).exists():
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            try:
                                item.unlink()
                            except OSError:
                                pass
            shutil.copytree(src, target, dirs_exist_ok=True)

        target_index = target / "index.html"
        if not target_index.exists() and not any(f for f in target.iterdir() if f.name != "cyan.log"):
            if default_template.exists():
                shutil.copy(default_template, target_index)
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
        return [sys.executable, "-u", str(main)]

    if site.site_type == "php":
        if not shutil.which("php"):
            raise SiteError("php is not installed on this host")
        return ["php", "-S", f"0.0.0.0:{site.port}", "-t", str(path)]

    if site.site_type == "react":
        if not shutil.which("npm"):
            raise SiteError("npm is not installed on this host (needed to build the React app)")
        package_json = path / "package.json"
        if not package_json.exists():
            raise SiteError("react site requires a package.json with a build script")
        subprocess.run(["npm", "install"], cwd=path, capture_output=True, text=True, timeout=300)
        build = subprocess.run(["npm", "run", "build"], cwd=path,
                                capture_output=True, text=True, timeout=300)
        if build.returncode != 0:
            raise SiteError(f"npm run build failed: {build.stderr[-2000:]}")
        # Create React App / Vite output directories, in order of likelihood.
        output_dir = next((path / d for d in ("build", "dist") if (path / d).is_dir()), None)
        if not output_dir:
            raise SiteError("build succeeded but no build/ or dist/ output directory was found")
        return [sys.executable, "-m", "http.server", str(site.port), "--directory", str(output_dir)]

    return None


def deploy_site(name: str) -> Website:
    session = get_session()
    try:
        site = session.query(Website).filter_by(name=name).first()
        if not site:
            raise SiteError(f"Site '{name}' not found")

        # Stop any process currently running for this site before
        # touching its folder — on Windows, a live process holding a file
        # handle inside the site directory (e.g. its own log file) blocks
        # any operation that needs to modify that directory, even ones
        # that no longer wipe it outright. Cheap and safe to call even
        # when nothing is running (stop_site tolerates that).
        if site.status == "running":
            session.close()
            try:
                stop_site(name)
            except SiteError:
                pass
            session = get_session()
            site = session.query(Website).filter_by(name=name).first()

        try:
            path = fetch_source(site)
        except SiteError as e:
            _log_event(session, site.id, "deploy", False, str(e))
            raise

        env = os.environ.copy()
        env.update(json.loads(site.env_vars or "{}"))
        env["PORT"] = str(site.port)
        repo_root = str(Path(__file__).resolve().parent.parent)
        env["CYAN_SERVER_ROOT"] = repo_root
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else repo_root

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
            popen_kwargs = {
                "cwd": path,
                "env": env,
            }
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                popen_kwargs["start_new_session"] = True

            with open(log_path, "a") as logf:
                proc = subprocess.Popen(
                    cmd,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    **popen_kwargs,
                )
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


def kill_process_tree(pid: int, timeout: float = 3.0) -> None:
    """Universally terminate a process and all of its spawned child processes
    across Windows, Linux, and macOS using psutil."""
    import psutil
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            parent.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass


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
            kill_process_tree(site.pid)

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


def set_domain(name: str, domain: str | None) -> Website:
    """Connect (or change, or clear with domain=None) a domain/subdomain
    for a site. Any hostname works here the same way — Caddy doesn't
    distinguish 'domain' from 'subdomain', both are just a hostname
    string in the generated Caddyfile — so 'api.example.com' works
    exactly like 'example.com'. Triggers a live Caddy reload so it takes
    effect immediately, no redeploy needed."""
    session = get_session()
    try:
        site = session.query(Website).filter_by(name=name).first()
        if not site:
            raise SiteError(f"Site '{name}' not found")
        site.domain = domain
        session.commit()
        _log_event(session, site.id, "set_domain", True, f"domain -> {domain}")
        all_sites = session.query(Website).all()
        session.refresh(site)
        result = site
    finally:
        session.close()

    reload_caddy(all_sites)
    return result


def delete_site(name: str, permanent: bool = False) -> None:
    """Stops the site if running, then moves its source folder + config
    to trash (30-day retention, same pattern as storage deletes) unless
    permanent=True. The DB row itself is removed either way — trash
    restore re-creates it from the saved metadata."""
    session = get_session()
    try:
        site = session.query(Website).filter_by(name=name).first()
        if not site:
            raise SiteError(f"Site '{name}' not found")
        site_snapshot = {
            "site_type": site.site_type, "source_type": site.source_type,
            "source": site.source, "port": site.port, "domain": site.domain,
            "env_vars": site.env_vars,
        }
    finally:
        session.close()

    try:
        stop_site(name)
    except SiteError:
        pass  # already stopped

    site_dir = _site_dir(name)

    session = get_session()
    try:
        site = session.query(Website).filter_by(name=name).first()
        if site:
            session.delete(site)
            session.commit()
    finally:
        session.close()

    if permanent:
        import shutil as _shutil
        if site_dir.exists():
            _shutil.rmtree(site_dir)
    elif site_dir.exists() and any(site_dir.iterdir()):
        from trash.manager import move_to_trash
        move_to_trash("website", name, name, site_dir, metadata=site_snapshot)
    elif site_dir.exists():
        site_dir.rmdir()  # empty dir, nothing worth trashing


def restore_site(trash_id: int) -> Website:
    """Re-creates a website's DB row from the trash item's saved
    metadata and moves its folder back, then redeploys it."""
    import json as _json
    from trash.manager import restore as trash_restore, get_trash_item, TrashError

    item = get_trash_item(trash_id)
    if item.item_type != "website":
        raise SiteError(f"Trash item {trash_id} is not a website")
    metadata = _json.loads(item.metadata_json or "{}")

    restore_to = get_sites_dir() / item.name  # NOT _site_dir() — that mkdirs, which
    # would leave an empty directory sitting exactly where restore needs to
    # move content back to, and restore refuses to overwrite anything present.
    try:
        trash_restore(trash_id, restore_to)
    except TrashError as e:
        raise SiteError(str(e))

    site = create_site(
        name=item.name, site_type=metadata["site_type"], source_type=metadata["source_type"],
        source=str(restore_to), port=metadata["port"], domain=metadata.get("domain"),
        env_vars=_json.loads(metadata.get("env_vars") or "{}"),
    )
    return deploy_site(item.name)


def list_sites() -> list[Website]:
    session = get_session()
    try:
        return session.query(Website).all()
    finally:
        session.close()


def recover_sites() -> list[dict]:
    """Bring every site that was marked 'running' before the agent last
    stopped back up for real (spec section 20: Automatic Recovery). A site
    row can say status='running' with a stale pid from a previous process
    that's now dead — e.g. after a reboot. This checks each one against
    the real process table / Docker and only redeploys what's actually
    down, so calling this twice in a row is safe (idempotent)."""
    results = []
    for site in list_sites():
        if site.status != "running":
            continue
        if _is_actually_running(site):
            results.append({"name": site.name, "action": "already_running"})
            continue
        try:
            deploy_site(site.name)
            results.append({"name": site.name, "action": "recovered"})
        except SiteError as e:
            results.append({"name": site.name, "action": "failed", "error": str(e)})
    return results


def _is_actually_running(site: Website) -> bool:
    if site.site_type == "docker":
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}",
                                  f"cyan-{site.name}"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and result.stdout.strip() == "true"

    # PID existence alone is unreliable — PIDs get reused (fast, in
    # containers especially), so a dead site's old PID can appear to
    # belong to a live, unrelated process. The authoritative signal for
    # "is this site actually serving" is whether something is listening
    # on its port right now.
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", site.port))
            return True
        except OSError:
            return False


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


# ---------------------------------------------------------------------------
# Site file manager — edit a deployed site's files directly (spec-adjacent:
# lets you fix a typo or swap an asset without a full git-push redeploy).
# Same path-traversal-safe pattern as storage/manager.py, scoped to one
# site's folder instead of the shared storage root.
# ---------------------------------------------------------------------------

def _site_safe_path(name: str, relative: str) -> Path:
    root = _site_dir(name).resolve()
    candidate = (root / relative.lstrip("/")).resolve()
    if root not in candidate.parents and candidate != root:
        raise SiteError("Path traversal rejected")
    return candidate


def list_site_files(name: str, relative: str = "") -> list[dict]:
    target = _site_safe_path(name, relative)
    if not target.exists():
        raise SiteError("Path does not exist")
    if not target.is_dir():
        raise SiteError("Path is not a directory")
    entries = []
    for item in sorted(target.iterdir()):
        stat = item.stat()
        entries.append({
            "name": item.name, "is_dir": item.is_dir(),
            "size_bytes": stat.st_size if item.is_file() else None,
        })
    return entries


def read_site_file(name: str, relative: str) -> bytes:
    target = _site_safe_path(name, relative)
    if not target.is_file():
        raise SiteError("Not a file")
    return target.read_bytes()


def write_site_file(name: str, relative: str, content: bytes) -> None:
    """Overwrites (or creates) a file within the site's folder. Live
    sites pick up static-file changes on next request — no redeploy
    needed for static/react (already-built) content; node/python/php
    apps that read files at startup would need a redeploy to see it."""
    target = _site_safe_path(name, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def delete_site_file(name: str, relative: str) -> None:
    target = _site_safe_path(name, relative)
    if not target.exists():
        raise SiteError("Path does not exist")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
