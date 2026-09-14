# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""Linux implementation of PackageManager. Detects apt/dnf/pacman and
never executes an install without a caller-confirmed InstallPlan."""
from __future__ import annotations

import shutil
import subprocess

from platform_impl.base import PackageManager, InstallPlan, CommandResult

_LINUX_MANAGERS = [
    ("apt-get", "apt"),
    ("dnf", "dnf"),
    ("yum", "yum"),
    ("pacman", "pacman"),
    ("zypper", "zypper"),
]


def _detect_manager() -> str | None:
    for binary, name in _LINUX_MANAGERS:
        if shutil.which(binary):
            return name
    return None


class LinuxPackageManager(PackageManager):
    def __init__(self):
        self.manager = _detect_manager()

    def is_installed(self, name: str) -> bool:
        return shutil.which(name) is not None

    def plan_install(self, name: str) -> InstallPlan:
        if not self.manager:
            return InstallPlan(
                packages=[name],
                method="none",
                requires_admin=True,
                summary=f"No supported package manager detected on this Linux "
                        f"system. Cannot auto-install '{name}'.",
            )
        return InstallPlan(
            packages=[name],
            method=self.manager,
            requires_admin=True,
            summary=f"Will run: sudo {self.manager} install -y {name}",
        )

    def install(self, plan: InstallPlan) -> CommandResult:
        if plan.method == "none":
            return CommandResult(False, "", "No package manager available", 1)

        install_cmd = {
            "apt": ["apt-get", "install", "-y"],
            "dnf": ["dnf", "install", "-y"],
            "yum": ["yum", "install", "-y"],
            "pacman": ["pacman", "-S", "--noconfirm"],
            "zypper": ["zypper", "install", "-y"],
        }[plan.method]

        cmd = ["sudo"] + install_cmd + plan.packages
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        except subprocess.SubprocessError as e:
            return CommandResult(False, "", str(e), 1)
