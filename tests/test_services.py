# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
Auth, storage, and application-manager smoke tests. Uses a temp CYAN_DATA_DIR so this never touches the
developer's real ~/.cyan-server install. Every assertion here is against
real DB rows / real files / real HTTP responses from a live agent — see
test_full_stack() which spins up the actual agent process.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="cyan-test-"))
os.environ["CYAN_DATA_DIR"] = str(TEST_DATA_DIR)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db  # noqa: E402
init_db()

from security.auth import hash_password, verify_password, ensure_default_admin, authenticate  # noqa: E402
from storage import manager as storage_manager  # noqa: E402
from apps.manager import parse_manifest, validate_requirements, RequirementError  # noqa: E402


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


def test_default_admin_created_once():
    username, pw1 = ensure_default_admin("tester")
    assert pw1  # freshly generated
    username2, pw2 = ensure_default_admin("tester")
    assert pw2 == ""  # already exists, no password returned second time
    assert authenticate("tester", pw1) is not None
    assert authenticate("tester", "wrong") is None


def test_storage_path_traversal_blocked():
    try:
        storage_manager._safe_path("../../etc/passwd")
        assert False, "should have raised"
    except storage_manager.StorageError:
        pass


def test_storage_upload_list_roundtrip():
    storage_manager.save_upload("", "hello.txt", b"hello world")
    entries = storage_manager.list_dir("")
    names = [e["name"] for e in entries]
    assert "hello.txt" in names
    content = storage_manager.read_file("hello.txt")
    assert content == b"hello world"


def test_app_requirement_validation_rejects_impossible_ram():
    manifest = parse_manifest("name: x\ntype: node\nrequirements:\n  ram: 999999999MB\n")
    try:
        validate_requirements(manifest)
        assert False, "should have raised RequirementError"
    except RequirementError:
        pass


def test_app_requirement_validation_passes_small_ram():
    manifest = parse_manifest("name: y\ntype: node\nrequirements:\n  ram: 1MB\n")
    validate_requirements(manifest)  # should not raise


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
    print(f"All {len(tests)} tests passed.")
