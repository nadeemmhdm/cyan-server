# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""Trash/recycle bin tests: real files moved to a real trash directory and
back, real expiry-based purge logic — not mocked."""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-trash-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db, TrashItem, get_session  # noqa: E402
init_db()

from trash import manager as trash_manager  # noqa: E402


def test_move_to_trash_and_restore_roundtrip():
    src = Path(tempfile.mkdtemp()) / "myfile.txt"
    src.write_text("hello trash")

    item = trash_manager.move_to_trash("storage", "myfile.txt", "myfile.txt", src)
    assert not src.exists()  # moved, not copied
    assert Path(item.trash_path).exists()

    restore_to = src  # restore to the same original location
    restored = trash_manager.restore(item.id, restore_to)
    assert restore_to.exists()
    assert restore_to.read_text() == "hello trash"
    assert not Path(item.trash_path).exists()  # moved out of trash


def test_restore_missing_id_raises():
    try:
        trash_manager.restore(999999, Path("/tmp/nonexistent"))
        assert False, "should have raised"
    except trash_manager.TrashError:
        pass


def test_expired_items_get_purged_not_fresh_ones():
    fresh_src = Path(tempfile.mkdtemp()) / "fresh.txt"
    fresh_src.write_text("fresh")
    fresh_item = trash_manager.move_to_trash("storage", "fresh.txt", "fresh.txt", fresh_src)

    old_src = Path(tempfile.mkdtemp()) / "old.txt"
    old_src.write_text("old")
    old_item = trash_manager.move_to_trash("storage", "old.txt", "old.txt", old_src)

    # Backdate the "old" item's expiry as if it were deleted 31 days ago.
    session = get_session()
    try:
        row = session.query(TrashItem).filter_by(id=old_item.id).first()
        row.expires_at = datetime.utcnow() - timedelta(days=1)
        session.commit()
    finally:
        session.close()

    purged = trash_manager.purge_expired()
    assert "old.txt" in purged
    assert "fresh.txt" not in purged

    remaining = [i.name for i in trash_manager.list_trash()]
    assert "fresh.txt" in remaining
    assert "old.txt" not in remaining


if __name__ == "__main__":
    test_move_to_trash_and_restore_roundtrip()
    print("  ok  test_move_to_trash_and_restore_roundtrip")
    test_restore_missing_id_raises()
    print("  ok  test_restore_missing_id_raises")
    test_expired_items_get_purged_not_fresh_ones()
    print("  ok  test_expired_items_get_purged_not_fresh_ones")
    print("All trash tests passed.")
