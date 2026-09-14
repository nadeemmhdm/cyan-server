# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""Database Manager tests. SQLite is real (a genuine file, real sqlite3
connections, real queries) — Postgres path exists but isn't exercised here
since it needs a real postgres install (see database/manager.py docstring
for why the build sandbox couldn't verify it)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-db-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db  # noqa: E402
init_db()

import database.manager as db_manager  # noqa: E402


def test_create_sqlite_database_creates_real_file():
    db = db_manager.create_database("t1", "sqlite")
    assert db.engine == "sqlite"
    path = Path(__import__("json").loads(db.connection_info)["path"])
    assert path.exists()
    assert path.suffix == ".sqlite"


def test_duplicate_name_rejected():
    try:
        db_manager.create_database("t1", "sqlite")
        assert False, "should have raised"
    except db_manager.DatabaseError:
        pass


def test_query_create_table_and_insert_then_status_reflects_it():
    db_manager.execute_query("t1", "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    db_manager.execute_query("t1", "INSERT INTO users (name) VALUES ('alice')")
    db_manager.execute_query("t1", "INSERT INTO users (name) VALUES ('bob')")

    status = db_manager.get_status("t1")
    assert "users" in status["tables"]
    assert status["row_counts"]["users"] == 2

    result = db_manager.execute_query("t1", "SELECT name FROM users ORDER BY name")
    names = [r["name"] for r in result["rows"]]
    assert names == ["alice", "bob"]


def test_invalid_sql_raises_database_error():
    try:
        db_manager.execute_query("t1", "SELECT * FROM nonexistent_table")
        assert False, "should have raised"
    except db_manager.DatabaseError:
        pass


def test_delete_then_restore_roundtrip():
    db_manager.create_database("t2", "sqlite")
    db_manager.execute_query("t2", "CREATE TABLE items (id INTEGER PRIMARY KEY)")
    db_manager.execute_query("t2", "INSERT INTO items DEFAULT VALUES")

    db_manager.delete_database("t2")  # default: trash
    try:
        db_manager.get_database("t2")
        assert False, "should be gone from the active list"
    except db_manager.DatabaseError:
        pass

    from trash.manager import list_trash
    items = list_trash("database")
    assert any(i.name == "t2" for i in items)
    trash_id = next(i.id for i in items if i.name == "t2")

    restored = db_manager.restore_database(trash_id)
    assert restored.name == "t2"
    status = db_manager.get_status("t2")
    assert status["row_counts"]["items"] == 1  # data survived the round trip


def test_permanent_delete_removes_file_entirely():
    db = db_manager.create_database("t3", "sqlite")
    path = Path(__import__("json").loads(db.connection_info)["path"])
    db_manager.delete_database("t3", permanent=True)
    assert not path.exists()

    from trash.manager import list_trash
    assert not any(i.name == "t3" for i in list_trash("database"))


if __name__ == "__main__":
    tests = [
        test_create_sqlite_database_creates_real_file,
        test_duplicate_name_rejected,
        test_query_create_table_and_insert_then_status_reflects_it,
        test_invalid_sql_raises_database_error,
        test_delete_then_restore_roundtrip,
        test_permanent_delete_removes_file_entirely,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"All {len(tests)} database tests passed.")
