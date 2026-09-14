"""tunnel/connect.py tests. Neither cloudflared nor ngrok binaries are
available in this build sandbox (ngrok's own binary download isn't
reachable, cloudflared's isn't either) -- so what IS genuinely testable
here, and what these tests actually check for real: site-to-port lookup
against a real deployed site, and that missing a site / missing a
provider produces a clear error rather than a confusing one."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-tunnel-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db  # noqa: E402
init_db()

import web.manager as web_manager  # noqa: E402
import tunnel.connect as tunnel_connect  # noqa: E402


def test_get_site_port_finds_real_site():
    src = Path(tempfile.mkdtemp())
    (src / "index.html").write_text("<h1>tunnel test</h1>")
    web_manager.create_site("tunneldemo", "static", "folder", str(src), 19301)

    port = tunnel_connect.get_site_port("tunneldemo")
    assert port == 19301


def test_get_site_port_missing_site_raises_clear_error():
    try:
        tunnel_connect.get_site_port("does-not-exist")
        assert False, "should have raised"
    except tunnel_connect.TunnelConnectError as e:
        assert "not found" in str(e)
        assert "cyan web list" in str(e)  # points the user at the fix


def test_connect_to_cloudflare_without_cloudflared_raises_clear_error():
    import shutil
    if shutil.which("cloudflared"):
        print("  (skipped: cloudflared IS installed here)")
        return
    try:
        tunnel_connect.connect_site_to_cloudflare("tunneldemo", "demo.example.com", "my-tunnel")
        assert False, "should have raised"
    except tunnel_connect.TunnelConnectError as e:
        assert "cloudflared" in str(e).lower()


def test_connect_to_ngrok_without_ngrok_raises_clear_error():
    import shutil
    if shutil.which("ngrok"):
        print("  (skipped: ngrok IS installed here)")
        return
    try:
        tunnel_connect.connect_site_to_ngrok("tunneldemo")
        assert False, "should have raised"
    except tunnel_connect.TunnelConnectError as e:
        assert "ngrok" in str(e).lower()


if __name__ == "__main__":
    test_get_site_port_finds_real_site()
    print("  ok  test_get_site_port_finds_real_site")
    test_get_site_port_missing_site_raises_clear_error()
    print("  ok  test_get_site_port_missing_site_raises_clear_error")
    test_connect_to_cloudflare_without_cloudflared_raises_clear_error()
    print("  ok  test_connect_to_cloudflare_without_cloudflared_raises_clear_error")
    test_connect_to_ngrok_without_ngrok_raises_clear_error()
    print("  ok  test_connect_to_ngrok_without_ngrok_raises_clear_error")
    print("All tunnel-connect tests passed.")
