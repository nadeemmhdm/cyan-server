"""Windows implementation of NetworkManager."""
from __future__ import annotations

import socket

import psutil

from platform_impl.base import NetworkManager


class WindowsNetworkManager(NetworkManager):
    def is_port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    def list_open_ports(self) -> list[int]:
        ports = set()
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr:
                ports.add(conn.laddr.port)
        return sorted(ports)
