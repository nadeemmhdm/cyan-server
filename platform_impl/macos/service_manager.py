"""macOS implementation of ServiceManager, backed by launchctl."""
from __future__ import annotations

import subprocess

from platform_impl.base import ServiceManager, CommandResult


class MacServiceManager(ServiceManager):
    def _run(self, args: list[str]) -> CommandResult:
        try:
            result = subprocess.run(
                ["launchctl"] + args, capture_output=True, text=True, timeout=15
            )
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return CommandResult(False, "", str(e), 1)

    def start(self, service_name: str) -> CommandResult:
        return self._run(["start", service_name])

    def stop(self, service_name: str) -> CommandResult:
        return self._run(["stop", service_name])

    def restart(self, service_name: str) -> CommandResult:
        stop_result = self.stop(service_name)
        return self.start(service_name)

    def status(self, service_name: str) -> str:
        result = self._run(["list", service_name])
        if result.success:
            return "running"
        return "stopped"

    def enable_on_boot(self, service_name: str) -> CommandResult:
        return CommandResult(
            False, "", "launchd plist must be installed to ~/Library/LaunchAgents "
                       "for boot persistence; not auto-handled here", 1
        )
