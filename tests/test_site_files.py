# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""Site file manager tests. Real files, real path-traversal rejection
scoped to a single site's folder (not the shared storage root)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-sitefiles-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db  # noqa: E402
init_db()

import web.manager as web_manager  # noqa: E402


def test_list_and_read_site_files():
    src = Path(tempfile.mkdtemp())
    (src / "index.html").write_text("<h1>original</h1>")
    web_manager.create_site("filesite", "static", "folder", str(src), 19401)
    web_manager.deploy_site("filesite")

    entries = web_manager.list_site_files("filesite")
    names = [e["name"] for e in entries]
    assert "index.html" in names

    content = web_manager.read_site_file("filesite", "index.html")
    assert content == b"<h1>original</h1>"

    web_manager.stop_site("filesite")


def test_write_site_file_edits_in_place():
    web_manager.write_site_file("filesite", "index.html", b"<h1>edited</h1>")
    content = web_manager.read_site_file("filesite", "index.html")
    assert content == b"<h1>edited</h1>"


def test_write_creates_new_nested_file():
    web_manager.write_site_file("filesite", "assets/style.css", b"body { color: red; }")
    content = web_manager.read_site_file("filesite", "assets/style.css")
    assert content == b"body { color: red; }"


def test_delete_site_file():
    web_manager.delete_site_file("filesite", "assets/style.css")
    entries = web_manager.list_site_files("filesite", "assets")
    assert not any(e["name"] == "style.css" for e in entries)


def test_path_traversal_rejected():
    try:
        web_manager.read_site_file("filesite", "../../../etc/passwd")
        assert False, "should have raised"
    except web_manager.SiteError as e:
        assert "traversal" in str(e).lower()


def test_traversal_cannot_reach_a_different_sites_files():
    src2 = Path(tempfile.mkdtemp())
    (src2 / "secret.txt").write_text("top secret")
    web_manager.create_site("othersite", "static", "folder", str(src2), 19402)

    try:
        web_manager.read_site_file("filesite", "../othersite/secret.txt")
        assert False, "should have raised — one site must not read another's files"
    except web_manager.SiteError:
        pass


if __name__ == "__main__":
    test_list_and_read_site_files()
    print("  ok  test_list_and_read_site_files")
    test_write_site_file_edits_in_place()
    print("  ok  test_write_site_file_edits_in_place")
    test_write_creates_new_nested_file()
    print("  ok  test_write_creates_new_nested_file")
    test_delete_site_file()
    print("  ok  test_delete_site_file")
    test_path_traversal_rejected()
    print("  ok  test_path_traversal_rejected")
    test_traversal_cannot_reach_a_different_sites_files()
    print("  ok  test_traversal_cannot_reach_a_different_sites_files")
    print("All site-file-manager tests passed.")
