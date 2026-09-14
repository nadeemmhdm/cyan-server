# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Cyan Server - Platform Adapter Base Interfaces

Core application code must NEVER call subprocess/os.system directly for
package installation, service management, or networking. It must go
through these abstractions, which are implemented per-OS in
platform/windows, platform/linux, platform/macos.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class InstallPlan:
    """What would be installed, shown to the user before any action is taken."""
    packages: list[str]
    method: str          # e.g. "apt", "brew", "winget"
    requires_admin: bool
    summary: str


@dataclass
class CommandResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int


class PackageManager(ABC):
    """Abstraction over apt/dnf/pacman/brew/winget/choco."""

    @abstractmethod
    def is_installed(self, name: str) -> bool: ...

    @abstractmethod
    def plan_install(self, name: str) -> InstallPlan:
        """Build a plan WITHOUT executing anything. Caller must show this
        to the user and get confirmation before calling install()."""
        ...

    @abstractmethod
    def install(self, plan: InstallPlan) -> CommandResult:
        """Execute a previously-shown, user-confirmed InstallPlan."""
        ...


class ServiceManager(ABC):
    """Abstraction over systemd / launchd / Windows Services."""

    @abstractmethod
    def start(self, service_name: str) -> CommandResult: ...

    @abstractmethod
    def stop(self, service_name: str) -> CommandResult: ...

    @abstractmethod
    def restart(self, service_name: str) -> CommandResult: ...

    @abstractmethod
    def status(self, service_name: str) -> str:
        """Return one of: 'running', 'stopped', 'failed', 'unknown'."""
        ...

    @abstractmethod
    def enable_on_boot(self, service_name: str) -> CommandResult: ...


class NetworkManager(ABC):
    """Abstraction over platform networking (ports, firewall checks)."""

    @abstractmethod
    def is_port_available(self, port: int) -> bool: ...

    @abstractmethod
    def list_open_ports(self) -> list[int]: ...


def get_platform_adapters() -> tuple[PackageManager, ServiceManager, NetworkManager]:
    """Factory: returns the correct (PackageManager, ServiceManager,
    NetworkManager) triple for the currently running OS."""
    import platform as _platform
    system = _platform.system()

    if system == "Linux":
        from platform_impl.linux.package_manager import LinuxPackageManager
        from platform_impl.linux.service_manager import LinuxServiceManager
        from platform_impl.linux.network_manager import LinuxNetworkManager
        return LinuxPackageManager(), LinuxServiceManager(), LinuxNetworkManager()
    elif system == "Darwin":
        from platform_impl.macos.package_manager import MacPackageManager
        from platform_impl.macos.service_manager import MacServiceManager
        from platform_impl.macos.network_manager import MacNetworkManager
        return MacPackageManager(), MacServiceManager(), MacNetworkManager()
    elif system == "Windows":
        from platform_impl.windows.package_manager import WindowsPackageManager
        from platform_impl.windows.service_manager import WindowsServiceManager
        from platform_impl.windows.network_manager import WindowsNetworkManager
        return WindowsPackageManager(), WindowsServiceManager(), WindowsNetworkManager()
    else:
        raise RuntimeError(f"Unsupported platform: {system}")
