# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""macOS implementation of PackageManager, backed by Homebrew."""
from __future__ import annotations

import shutil
import subprocess

from platform_impl.base import PackageManager, InstallPlan, CommandResult


class MacPackageManager(PackageManager):
    def __init__(self):
        self.brew = shutil.which("brew")

    def is_installed(self, name: str) -> bool:
        return shutil.which(name) is not None

    def plan_install(self, name: str) -> InstallPlan:
        if not self.brew:
            return InstallPlan(
                packages=[name],
                method="none",
                requires_admin=False,
                summary=f"Homebrew not found. Cannot auto-install '{name}'. "
                        f"Install Homebrew first (https://brew.sh).",
            )
        return InstallPlan(
            packages=[name],
            method="brew",
            requires_admin=False,
            summary=f"Will run: brew install {name}",
        )

    def install(self, plan: InstallPlan) -> CommandResult:
        if plan.method == "none":
            return CommandResult(False, "", "Homebrew not available", 1)
        cmd = ["brew", "install"] + plan.packages
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
