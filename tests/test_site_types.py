"""Tests for the php and react site types added to web/manager.py.
React is live-tested for real (npm install + npm run build + serve the
real output directory — no react dependency needed to test the pipeline
itself, just a package.json with a build script). PHP could not be
live-tested here (same broken package mirror that blocked Postgres in an
earlier session also blocks php-cli) — this only checks the missing-binary
error path, which doesn't need php installed to verify."""
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-sitetypes-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db  # noqa: E402
init_db()

import web.manager as web_manager  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_php_missing_binary_raises_clear_error():
    if shutil.which("php"):
        print("  (skipped: php IS installed here, this test targets the missing-binary path)")
        return
    src = Path(tempfile.mkdtemp())
    (src / "index.php").write_text("<?php echo 'hi'; ?>")
    port = _free_port()
    web_manager.create_site("phptest", "php", "folder", str(src), port)
    try:
        web_manager.deploy_site("phptest")
        assert False, "should have raised — php is not installed in this test env"
    except web_manager.SiteError as e:
        assert "php is not installed" in str(e)


def test_react_build_and_serve_pipeline():
    if not shutil.which("npm"):
        print("  (skipped: npm not available in this environment)")
        return
    src = Path(tempfile.mkdtemp())
    (src / "package.json").write_text(
        '{"name": "t", "version": "1.0.0", '
        '"scripts": {"build": "node -e \\"const fs=require(\'fs\'); fs.mkdirSync(\'dist\', {recursive:true}); fs.copyFileSync(\'index.html\', \'dist/index.html\');\\""}}'
    )
    (src / "index.html").write_text("<h1>react test</h1>")

    port = _free_port()
    web_manager.create_site("reacttest", "react", "folder", str(src), port)
    site = web_manager.deploy_site("reacttest")
    assert site.status == "running"

    import time
    import urllib.request
    body = None
    for _ in range(10):
        try:
            body = urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=2).read().decode()
            break
        except Exception:
            time.sleep(0.5)
    assert body is not None
    assert "react test" in body

    web_manager.stop_site("reacttest")


def test_react_without_package_json_raises():
    src = Path(tempfile.mkdtemp())  # no package.json
    web_manager.create_site("reactbroken", "react", "folder", str(src), _free_port())
    try:
        web_manager.deploy_site("reactbroken")
        assert False, "should have raised"
    except web_manager.SiteError as e:
        assert "package.json" in str(e)


if __name__ == "__main__":
    test_php_missing_binary_raises_clear_error()
    print("  ok  test_php_missing_binary_raises_clear_error")
    test_react_build_and_serve_pipeline()
    print("  ok  test_react_build_and_serve_pipeline")
    test_react_without_package_json_raises()
    print("  ok  test_react_without_package_json_raises")
    print("All site-type tests passed.")
