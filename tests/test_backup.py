"""Backup/restore tests. Real tar.gz archives, a real SQLite backup-API
snapshot (not a raw file copy), and a real extract-and-verify round trip
-- including simulating actual data loss and confirming restore recovers
it, and confirming path-traversal members get rejected."""
import os
import sys
import tarfile
import tempfile
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-backup-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db, Website, get_session  # noqa: E402
init_db()

import backup.manager as backup_manager  # noqa: E402


def _data_dir() -> Path:
    return Path(os.environ["CYAN_DATA_DIR"])


def test_create_backup_contains_expected_members():
    # Put some real content in place first.
    sites_dir = _data_dir() / "sites" / "mysite"
    sites_dir.mkdir(parents=True, exist_ok=True)
    (sites_dir / "index.html").write_text("<h1>backup me</h1>")

    session = get_session()
    session.add(Website(name="mysite", site_type="static", source_type="folder",
                         source=str(sites_dir), port=19001, status="stopped"))
    session.commit()
    session.close()

    backup_dir = Path(tempfile.mkdtemp())
    archive = backup_manager.create_backup(destination=backup_dir)
    assert archive.exists()
    assert archive.name.startswith("cyan-backup-")

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        assert "cyan.db" in names
        assert any(n.startswith("sites/mysite") for n in names)


def test_restore_recovers_deleted_data():
    backup_dir = Path(tempfile.mkdtemp())
    archive = backup_manager.create_backup(destination=backup_dir)

    # Simulate real data loss: delete the site folder and wipe the DB.
    import shutil
    shutil.rmtree(_data_dir() / "sites")
    (_data_dir() / "cyan.db").unlink()
    assert not (_data_dir() / "sites" / "mysite" / "index.html").exists()

    result = backup_manager.restore_backup(archive, data_dir=_data_dir())
    assert result["restored_from"] == str(archive)

    restored_file = _data_dir() / "sites" / "mysite" / "index.html"
    assert restored_file.exists()
    assert restored_file.read_text() == "<h1>backup me</h1>"
    assert (_data_dir() / "cyan.db").exists()

    # The DB itself should be queryable and contain the site row that was
    # in it at backup time.
    session = get_session()
    try:
        site = session.query(Website).filter_by(name="mysite").first()
        assert site is not None
        assert site.port == 19001
    finally:
        session.close()


def test_restore_preserves_existing_state_instead_of_deleting():
    backup_dir = Path(tempfile.mkdtemp())
    archive = backup_manager.create_backup(destination=backup_dir)

    # Current sites/ still exists (from the previous test) — restoring
    # again should move it aside, not silently destroy it.
    result = backup_manager.restore_backup(archive, data_dir=_data_dir())
    assert result["preserved_previous_state_at"] is not None
    preserved_dir = _data_dir() / result["preserved_previous_state_at"]
    assert preserved_dir.exists()


def test_retention_pruning_keeps_only_newest():
    backup_dir = Path(tempfile.mkdtemp())
    import time
    paths = []
    for _ in range(5):
        paths.append(backup_manager.create_backup(destination=backup_dir))
        time.sleep(1.1)  # filenames are second-resolution timestamps

    removed = backup_manager.prune_backups(destination=backup_dir, retention_count=2)
    assert len(removed) == 3
    remaining = backup_manager.list_backups(destination=backup_dir)
    assert len(remaining) == 2
    # The two newest should be the survivors.
    assert remaining[0]["filename"] == paths[-1].name


def test_path_traversal_member_rejected():
    backup_dir = Path(tempfile.mkdtemp())
    evil_archive = backup_dir / "evil.tar.gz"
    with tarfile.open(evil_archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="../../etc/passwd")
        data = b"pwned"
        info.size = len(data)
        import io
        tar.addfile(info, io.BytesIO(data))

    try:
        backup_manager.restore_backup(evil_archive, data_dir=_data_dir())
        assert False, "should have raised BackupError"
    except backup_manager.BackupError:
        pass


if __name__ == "__main__":
    tests = [
        test_create_backup_contains_expected_members,
        test_restore_recovers_deleted_data,
        test_restore_preserves_existing_state_instead_of_deleting,
        test_retention_pruning_keeps_only_newest,
        test_path_traversal_member_rejected,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"All {len(tests)} backup tests passed.")
