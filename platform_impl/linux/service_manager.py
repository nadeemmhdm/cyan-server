"""Linux implementation of ServiceManager, backed by systemd."""
from __future__ import annotations

import shutil
import subprocess

from platform_impl.base import ServiceManager, CommandResult


class LinuxServiceManager(ServiceManager):
    def __init__(self):
        self.systemctl = shutil.which("systemctl")

    def _run(self, args: list[str]) -> CommandResult:
        if not self.systemctl:
            return CommandResult(False, "", "systemctl not found (non-systemd system)", 1)
        try:
            result = subprocess.run(
                [self.systemctl] + args, capture_output=True, text=True, timeout=15
            )
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        except subprocess.SubprocessError as e:
            return CommandResult(False, "", str(e), 1)

    def start(self, service_name: str) -> CommandResult:
        return self._run(["start", service_name])

    def stop(self, service_name: str) -> CommandResult:
        return self._run(["stop", service_name])

    def restart(self, service_name: str) -> CommandResult:
        return self._run(["restart", service_name])

    def status(self, service_name: str) -> str:
        if not self.systemctl:
            return "unknown"
        try:
            result = subprocess.run(
                [self.systemctl, "is-active", service_name],
                capture_output=True, text=True, timeout=10,
            )
            state = result.stdout.strip()
            if state == "active":
                return "running"
            if state in ("inactive", "dead"):
                return "stopped"
            if state == "failed":
                return "failed"
            return "unknown"
        except subprocess.SubprocessError:
            return "unknown"

    def enable_on_boot(self, service_name: str) -> CommandResult:
        return self._run(["enable", service_name])
