# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""Windows implementation of PackageManager, backed by winget (falls back
to choco if winget is unavailable)."""
from __future__ import annotations

import shutil
import subprocess

from platform_impl.base import PackageManager, InstallPlan, CommandResult


def _detect_manager() -> str | None:
    if shutil.which("winget"):
        return "winget"
    if shutil.which("choco"):
        return "choco"
    return None


class WindowsPackageManager(PackageManager):
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
                summary=f"Neither winget nor choco found. Cannot auto-install '{name}'.",
            )
        return InstallPlan(
            packages=[name],
            method=self.manager,
            requires_admin=True,
            summary=f"Will run: {self.manager} install {name}",
        )

    def install(self, plan: InstallPlan) -> CommandResult:
        if plan.method == "none":
            return CommandResult(False, "", "No package manager available", 1)

        cmd_map = {
            "winget": ["winget", "install", "--silent", "--accept-package-agreements",
                       "--accept-source-agreements"],
            "choco": ["choco", "install", "-y"],
        }
        cmd = cmd_map[plan.method] + plan.packages
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
