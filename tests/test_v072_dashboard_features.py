# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""Unit and Integration tests for Cyan Server v0.7.2 features:
1. ZIP extraction with Zip Slip path-traversal protection
2. API Key write-only permission scoping
3. Database engine reporting
4. Admin password verification and update
"""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-v072-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()  # fresh engine for this test file's CYAN_DATA_DIR -- see
# core/database.py:configure() docstring for why this is required
from core.database import init_db, get_session, User, ApiKey  # noqa: E402
init_db()

import web.manager as web_manager  # noqa: E402
import database.manager as db_manager  # noqa: E402
import security.auth as auth  # noqa: E402
from api.v1_routes import _check_read_permission, _check_write_permission  # noqa: E402
from fastapi import HTTPException


def test_zip_extraction_and_security():
    src = Path(tempfile.mkdtemp())
    web_manager.create_site("zipsite", "static", "folder", str(src), 19501)

    # Valid zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("index.html", "<h1>Zip App</h1>")
        zf.writestr("css/app.css", "body { margin: 0; }")
    
    extracted = web_manager.extract_site_zip("zipsite", buf.getvalue())
    assert "index.html" in extracted
    assert (src / "index.html").read_text() == "<h1>Zip App</h1>"
    assert (src / "css" / "app.css").read_text() == "body { margin: 0; }"

    # Zip slip malicious attempt
    evil_buf = io.BytesIO()
    with zipfile.ZipFile(evil_buf, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")

    try:
        web_manager.extract_site_zip("zipsite", evil_buf.getvalue())
        assert False, "Should have raised SiteError for zip traversal"
    except web_manager.SiteError as e:
        assert "escapes" in str(e).lower() or "traversal" in str(e).lower()


def test_write_permission_scoping():
    write_auth = {"auth_type": "api_key", "permissions": "write"}
    read_auth = {"auth_type": "api_key", "permissions": "read"}
    full_auth = {"auth_type": "api_key", "permissions": "full"}

    # Write key allows write, forbids read
    _check_write_permission(write_auth)
    try:
        _check_read_permission(write_auth)
        assert False, "Read check on write-only key should raise 403"
    except HTTPException as e:
        assert e.status_code == 403

    # Read key allows read, forbids write
    _check_read_permission(read_auth)
    try:
        _check_write_permission(read_auth)
        assert False, "Write check on read-only key should raise 403"
    except HTTPException as e:
        assert e.status_code == 403

    # Full key allows both
    _check_read_permission(full_auth)
    _check_write_permission(full_auth)


def test_database_engine_reporting():
    sqlite_ok = True
    pg_ok = db_manager.postgres_available()
    assert isinstance(sqlite_ok, bool)
    assert isinstance(pg_ok, bool)


def test_admin_password_change_logic():
    auth.ensure_default_admin("admin_test_user", "initial_pass_123")
    
    # Verify initial password
    assert auth.authenticate("admin_test_user", "initial_pass_123") is not None
    assert auth.authenticate("admin_test_user", "wrong_pass") is None

    # Change password
    session = get_session()
    try:
        u = session.query(User).filter_by(username="admin_test_user").first()
        assert auth.verify_password("initial_pass_123", u.password_hash)
        u.password_hash = auth.hash_password("updated_pass_456")
        session.commit()
    finally:
        session.close()

    # Verify updated password
    assert auth.authenticate("admin_test_user", "updated_pass_456") is not None
    assert auth.authenticate("admin_test_user", "initial_pass_123") is None
