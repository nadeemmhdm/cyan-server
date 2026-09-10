"""Smoke tests: detection must return real, self-consistent values on any
platform this runs on. These are not mocked — they assert against the
actual live host."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.detection import gather_system_report
from platform_impl.base import get_platform_adapters


def test_system_report_has_real_values():
    report = gather_system_report()
    assert report.os_name in ("windows", "linux", "macos")
    assert report.ram_total_gb > 0
    assert report.ram_available_gb >= 0
    assert report.ram_available_gb <= report.ram_total_gb
    assert report.cpu_cores_logical >= 1
    assert report.resource_profile in ("low", "balanced", "performance")
    assert isinstance(report.disks, list) and len(report.disks) >= 1
    assert isinstance(report.network_interfaces, list)


def test_platform_adapters_load_for_current_os():
    pkg_mgr, svc_mgr, net_mgr = get_platform_adapters()
    assert pkg_mgr is not None
    assert svc_mgr is not None
    ports = net_mgr.list_open_ports()
    assert isinstance(ports, list)


def test_resource_profile_thresholds():
    from core.detection import compute_resource_profile
    assert compute_resource_profile(2) == "low"
    assert compute_resource_profile(8) == "balanced"
    assert compute_resource_profile(32) == "performance"


if __name__ == "__main__":
    test_system_report_has_real_values()
    test_platform_adapters_load_for_current_os()
    test_resource_profile_thresholds()
    print("All tests passed.")
