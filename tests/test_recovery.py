"""Test the recovery/liveness-detection fix: PID existence alone is not a
reliable 'is this site running' signal (PIDs get reused, especially fast
in containers) — the real check has to be port-level."""
import http.server
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-recovery-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import init_db, Website, get_session  # noqa: E402
init_db()

from web.manager import _is_actually_running  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_detects_running_site_by_port():
    port = _free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        site = Website(name="t1", site_type="static", source_type="folder",
                        source="/tmp", port=port, status="running")
        assert _is_actually_running(site) is True
    finally:
        server.shutdown()


def test_detects_dead_site_even_with_stale_pid_field():
    """The core regression this guards: a site row can carry a pid that
    now belongs to an unrelated live process (PID reuse). Liveness must
    be judged by the port, not the pid field."""
    port = _free_port()  # nothing is listening on this port
    site = Website(name="t2", site_type="static", source_type="folder",
                    source="/tmp", port=port, status="running", pid=os.getpid())
    # os.getpid() is very much alive — if the code used PID existence
    # alone, this would incorrectly report "running".
    assert _is_actually_running(site) is False


if __name__ == "__main__":
    test_detects_running_site_by_port()
    print("  ok  test_detects_running_site_by_port")
    test_detects_dead_site_even_with_stale_pid_field()
    print("  ok  test_detects_dead_site_even_with_stale_pid_field")
    print("All recovery tests passed.")
