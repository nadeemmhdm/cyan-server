"""
Cyan Server - Core System Detection
Platform-independent hardware/OS/network detection.
Never assumes a specific OS. All values are read from the real host.
"""
from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import psutil


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class NetworkInterface:
    name: str
    address: Optional[str]
    netmask: Optional[str]
    is_up: bool
    speed_mbps: Optional[int] = None


@dataclass
class DiskInfo:
    mountpoint: str
    device: str
    fstype: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent_used: float


@dataclass
class SystemReport:
    os_name: str              # "windows" | "linux" | "macos"
    os_version: str
    os_release: str
    hostname: str
    architecture: str         # "x86_64" | "arm64" | ...
    cpu_model: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    ram_total_gb: float
    ram_available_gb: float
    disks: list[DiskInfo]
    network_interfaces: list[NetworkInterface]
    primary_ip: Optional[str]
    docker_available: bool
    docker_version: Optional[str]
    virtualization: Optional[str]
    resource_profile: str     # "low" | "balanced" | "performance"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_os() -> tuple[str, str, str]:
    """Return (os_name, os_version, os_release) using real platform data."""
    system = platform.system()
    if system == "Windows":
        os_name = "windows"
        os_version = platform.win32_ver()[1] or platform.version()
        os_release = platform.win32_ver()[0] or platform.release()
    elif system == "Darwin":
        os_name = "macos"
        os_version = platform.mac_ver()[0]
        os_release = platform.release()
    elif system == "Linux":
        os_name = "linux"
        os_release = platform.release()
        os_version = _linux_distro_version()
    else:
        os_name = system.lower()
        os_version = platform.version()
        os_release = platform.release()
    return os_name, os_version, os_release


def _linux_distro_version() -> str:
    """Read /etc/os-release if present; fall back to platform.version()."""
    os_release_path = Path("/etc/os-release")
    if os_release_path.exists():
        data = {}
        for line in os_release_path.read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k] = v.strip('"')
        name = data.get("NAME", "")
        version = data.get("VERSION", "")
        if name or version:
            return f"{name} {version}".strip()
    return platform.version()


def detect_architecture() -> str:
    machine = platform.machine().lower()
    mapping = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "arm32",
    }
    return mapping.get(machine, machine)


def detect_cpu() -> tuple[str, int, int]:
    cpu_model = platform.processor() or ""
    if not cpu_model and platform.system() == "Linux":
        cpu_model = _read_linux_cpu_model()
    physical = psutil.cpu_count(logical=False) or 1
    logical = psutil.cpu_count(logical=True) or 1
    return cpu_model or "Unknown CPU", physical, logical


def _read_linux_cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return ""


def detect_ram() -> tuple[float, float]:
    vm = psutil.virtual_memory()
    return round(vm.total / (1024 ** 3), 2), round(vm.available / (1024 ** 3), 2)


def detect_disks() -> list[DiskInfo]:
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append(
            DiskInfo(
                mountpoint=part.mountpoint,
                device=part.device,
                fstype=part.fstype,
                total_gb=round(usage.total / (1024 ** 3), 2),
                used_gb=round(usage.used / (1024 ** 3), 2),
                free_gb=round(usage.free / (1024 ** 3), 2),
                percent_used=usage.percent,
            )
        )
    return disks


def detect_network_interfaces() -> list[NetworkInterface]:
    interfaces = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        ipv4 = next((a for a in addrs if a.family == socket.AF_INET), None)
        st = stats.get(name)
        interfaces.append(
            NetworkInterface(
                name=name,
                address=ipv4.address if ipv4 else None,
                netmask=ipv4.netmask if ipv4 else None,
                is_up=st.isup if st else False,
                speed_mbps=st.speed if st and st.speed > 0 else None,
            )
        )
    return interfaces


def detect_primary_ip() -> Optional[str]:
    """Best-effort primary outbound IP without sending real traffic (UDP connect trick)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def detect_docker() -> tuple[bool, Optional[str]]:
    docker_path = shutil.which("docker")
    if not docker_path:
        return False, None
    try:
        result = subprocess.run(
            [docker_path, "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, result.stdout.strip()
        return False, None
    except (subprocess.SubprocessError, OSError):
        return False, None


def detect_virtualization() -> Optional[str]:
    """Detect if running in a VM/container. Best-effort, platform-specific."""
    system = platform.system()
    if system == "Linux":
        try:
            result = subprocess.run(
                ["systemd-detect-virt"], capture_output=True, text=True, timeout=2
            )
            val = result.stdout.strip()
            if val and val != "none":
                return val
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass
        if Path("/.dockerenv").exists():
            return "docker"
    return None


def compute_resource_profile(ram_total_gb: float) -> str:
    if ram_total_gb < 4:
        return "low"
    if ram_total_gb < 16:
        return "balanced"
    return "performance"


def gather_system_report() -> SystemReport:
    """Run all detection routines and assemble a SystemReport from real data."""
    os_name, os_version, os_release = detect_os()
    arch = detect_architecture()
    cpu_model, phys_cores, log_cores = detect_cpu()
    ram_total, ram_available = detect_ram()
    disks = detect_disks()
    interfaces = detect_network_interfaces()
    primary_ip = detect_primary_ip()
    docker_available, docker_version = detect_docker()
    virtualization = detect_virtualization()
    profile = compute_resource_profile(ram_total)

    return SystemReport(
        os_name=os_name,
        os_version=os_version,
        os_release=os_release,
        hostname=socket.gethostname(),
        architecture=arch,
        cpu_model=cpu_model,
        cpu_cores_physical=phys_cores,
        cpu_cores_logical=log_cores,
        ram_total_gb=ram_total,
        ram_available_gb=ram_available,
        disks=disks,
        network_interfaces=interfaces,
        primary_ip=primary_ip,
        docker_available=docker_available,
        docker_version=docker_version,
        virtualization=virtualization,
        resource_profile=profile,
    )


if __name__ == "__main__":
    import json
    report = gather_system_report()
    print(json.dumps(report.to_dict(), indent=2))
