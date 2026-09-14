"""Website delete-to-trash / restore-from-trash tests. Real files, real DB
rows, real Caddy config regeneration. Specifically guards against a real
bug caught during live testing: web/manager.py::_site_dir() auto-creates
its directory, so restore_site() must NOT use it to compute the restore
destination -- an empty pre-created dir there blocks the actual restore
(trash.manager.restore refuses to overwrite anything that exists)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-web-trash-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db  # noqa: E402
init_db()

import web.manager as web_manager  # noqa: E402


def test_delete_then_restore_site_roundtrip():
    src = Path(tempfile.mkdtemp())
    (src / "index.html").write_text("<h1>test site</h1>")

    site = web_manager.create_site("t1", "static", "folder", str(src), 18901, domain="t1.example.local")
    web_manager.deploy_site("t1")

    web_manager.delete_site("t1")  # default: trash, not permanent
    assert web_manager.list_sites() == []

    from trash.manager import list_trash
    trash_items = list_trash("website")
    assert len(trash_items) == 1
    assert trash_items[0].name == "t1"

    restored = web_manager.restore_site(trash_items[0].id)
    assert restored.name == "t1"
    assert restored.domain == "t1.example.local"  # metadata survived the round trip
    assert restored.status == "running"  # restore_site redeploys

    restored_index = Path(os.environ["CYAN_DATA_DIR"]) / "sites" / "t1" / "index.html"
    assert restored_index.exists()
    assert restored_index.read_text() == "<h1>test site</h1>"

    web_manager.stop_site("t1")


def test_permanent_delete_skips_trash():
    src = Path(tempfile.mkdtemp())
    (src / "index.html").write_text("gone forever")
    web_manager.create_site("t2", "static", "folder", str(src), 18902)
    web_manager.deploy_site("t2")

    web_manager.delete_site("t2", permanent=True)

    from trash.manager import list_trash
    assert not any(i.name == "t2" for i in list_trash("website"))


if __name__ == "__main__":
    test_delete_then_restore_site_roundtrip()
    print("  ok  test_delete_then_restore_site_roundtrip")
    test_permanent_delete_skips_trash()
    print("  ok  test_permanent_delete_skips_trash")
    print("All website-trash tests passed.")
