# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Cyan Server - Application Manager
Manifest-driven app installs (spec section 8). Validates requirements
against the REAL SystemReport from core.detection before installing
anything — this is where the Application Manager and hardware detection
are directly wired together, not just living in the same repo.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import Application, get_session
from core.detection import gather_system_report


class AppError(Exception):
    pass


class RequirementError(AppError):
    pass


def parse_manifest(manifest_yaml: str) -> dict:
    try:
        data = yaml.safe_load(manifest_yaml)
    except yaml.YAMLError as e:
        raise AppError(f"Invalid manifest YAML: {e}")
    for field in ("name", "type"):
        if field not in data:
            raise AppError(f"Manifest missing required field: {field}")
    return data


def _parse_size_mb(value) -> float:
    """Parse '512MB', '1GB', or a bare number (MB) into megabytes."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().upper()
    if s.endswith("GB"):
        return float(s[:-2]) * 1024
    if s.endswith("MB"):
        return float(s[:-2])
    return float(s)


def validate_requirements(manifest: dict) -> None:
    """Check manifest.requirements against the LIVE system report. Raises
    RequirementError with the same shape the spec's UI text shows
    ('Required RAM: X / Available RAM: Y')."""
    reqs = manifest.get("requirements", {})
    if not reqs:
        return

    report = gather_system_report()

    if "ram" in reqs:
        required_mb = _parse_size_mb(reqs["ram"])
        available_mb = report.ram_available_gb * 1024
        if required_mb > available_mb:
            raise RequirementError(
                f"Required RAM: {required_mb:.0f} MB\n"
                f"Available RAM: {available_mb:.0f} MB"
            )

    if "storage" in reqs:
        required_mb = _parse_size_mb(reqs["storage"])
        # use the disk backing the storage root
        from storage.manager import get_root
        root = get_root()
        usage = shutil.disk_usage(root)
        available_mb = usage.free / (1024 ** 2)
        if required_mb > available_mb:
            raise RequirementError(
                f"Required Storage: {required_mb:.0f} MB\n"
                f"Available Storage: {available_mb:.0f} MB"
            )

    app_type = manifest.get("type")
    if app_type in ("docker", "docker_compose") and not report.docker_available:
        raise RequirementError(
            "This application requires Docker, which is not available on this host."
        )


def install_app(manifest_yaml: str) -> Application:
    manifest = parse_manifest(manifest_yaml)
    validate_requirements(manifest)  # raises RequirementError, shown to user before anything runs

    session = get_session()
    try:
        if session.query(Application).filter_by(name=manifest["name"]).first():
            raise AppError(f"Application '{manifest['name']}' already installed")
        app = Application(
            name=manifest["name"], app_type=manifest["type"],
            manifest_yaml=manifest_yaml, status="stopped",
        )
        session.add(app)
        session.commit()
        session.refresh(app)
        return app
    finally:
        session.close()


def start_app(name: str) -> Application:
    session = get_session()
    try:
        app = session.query(Application).filter_by(name=name).first()
        if not app:
            raise AppError(f"Application '{name}' not found")
        manifest = parse_manifest(app.manifest_yaml)

        if app.app_type == "docker":
            if not shutil.which("docker"):
                raise AppError("Docker is not installed")
            image = manifest["image"]
            ports = manifest.get("ports", [])
            cmd = ["docker", "run", "-d", "--name", f"cyan-app-{name}"]
            for p in ports:
                cmd += ["-p", f"{p}:{p}"]
            cmd.append(image)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode != 0:
                raise AppError(f"docker run failed: {result.stderr}")
            app.container_id = result.stdout.strip()
            app.status = "running"

        elif app.app_type == "docker_compose":
            if not shutil.which("docker"):
                raise AppError("Docker is not installed")
            compose_path = manifest.get("compose_file")
            if not compose_path or not Path(compose_path).exists():
                raise AppError("compose_file not found")
            result = subprocess.run(
                ["docker", "compose", "-f", compose_path, "up", "-d"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                raise AppError(f"docker compose up failed: {result.stderr}")
            app.status = "running"

        else:
            raise AppError(f"Unsupported app_type for start: {app.app_type}")

        session.commit()
        session.refresh(app)
        return app
    finally:
        session.close()


def stop_app(name: str) -> Application:
    session = get_session()
    try:
        app = session.query(Application).filter_by(name=name).first()
        if not app:
            raise AppError(f"Application '{name}' not found")

        if app.app_type == "docker":
            subprocess.run(["docker", "stop", f"cyan-app-{name}"], capture_output=True, timeout=30)
            subprocess.run(["docker", "rm", f"cyan-app-{name}"], capture_output=True, timeout=30)
        elif app.app_type == "docker_compose":
            manifest = parse_manifest(app.manifest_yaml)
            compose_path = manifest.get("compose_file")
            if compose_path and Path(compose_path).exists():
                subprocess.run(["docker", "compose", "-f", compose_path, "down"],
                                capture_output=True, timeout=60)

        app.status = "stopped"
        app.container_id = None
        session.commit()
        session.refresh(app)
        return app
    finally:
        session.close()


def list_apps() -> list[Application]:
    session = get_session()
    try:
        return session.query(Application).all()
    finally:
        session.close()


def recover_apps() -> list[dict]:
    """Same idempotent recovery pattern as web/manager.py::recover_sites(),
    for Docker/Compose applications."""
    results = []
    for a in list_apps():
        if a.status != "running":
            continue
        if a.app_type == "docker" and a.container_id:
            check = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}",
                                     f"cyan-app-{a.name}"], capture_output=True, text=True, timeout=10)
            if check.returncode == 0 and check.stdout.strip() == "true":
                results.append({"name": a.name, "action": "already_running"})
                continue
        try:
            start_app(a.name)
            results.append({"name": a.name, "action": "recovered"})
        except AppError as e:
            results.append({"name": a.name, "action": "failed", "error": str(e)})
    return results
