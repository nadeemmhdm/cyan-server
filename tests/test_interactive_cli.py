# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""
End-to-End Test for Interactive CLI Features and Reboot Auto-Resume
Tests:
1. Default index.html starter page auto-creation
2. Port allocation
3. Database unique ID generation & query
4. Storage bucket unique ID generation & file upload
5. resume_all_services() reboot recovery
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

from cli.interactive import auto_create_default_index, get_next_available_port, _api_get, _api_post
from tunnel.state import resume_all_services, record_tunnel_route, load_tunnel_state

def test_interactive_features():
    print("[1] Testing auto_create_default_index...")
    with tempfile.TemporaryDirectory() as tmpdir:
        target_dir = Path(tmpdir) / "my-test-site"
        index_file = auto_create_default_index(target_dir, "my-test-site", 8089)
        assert index_file.exists(), "index.html should exist"
        content = index_file.read_text(encoding="utf-8")
        assert "my-test-site" in content, "Site name should be embedded in index.html"
        print("    ✓ Default page auto-created successfully with responsive template!")

    print("[2] Testing port allocator...")
    free_port = get_next_available_port(8080)
    assert free_port >= 8080, "Free port should be >= 8080"
    print(f"    ✓ Found available port: {free_port}")

    print("[3] Testing Database creation with unique ID...")
    db_res = _api_post("/api/database", {"name": "testcli", "engine": "sqlite"})
    db_uid = db_res.get("unique_id")
    assert db_uid and "testcli_" in db_uid, f"Expected unique ID format testcli_XXXX, got {db_uid}"
    print(f"    ✓ Database provisioned with unique ID: {db_uid}")

    # Query test
    q_res = _api_post(f"/api/database/{db_uid}/query", {"sql": "SELECT 123 AS num;"})
    assert q_res.get("rows") == [{"num": 123}], f"Query failed: {q_res}"
    print("    ✓ SQL Query executed successfully")

    # Cleanup DB
    _api_post(f"/api/database/{db_uid}?permanent=true", method="DELETE")
    print(f"    ✓ Cleaned up test database {db_uid}")

    print("[4] Testing Storage Bucket creation with unique ID...")
    b_res = _api_post("/api/storage/buckets", {"name": "testbucket", "description": "CLI test"})
    b_uid = b_res.get("unique_id")
    assert b_uid and "testbucket_" in b_uid, f"Expected unique ID format testbucket_XXXX, got {b_uid}"
    print(f"    ✓ Storage bucket provisioned with unique ID: {b_uid}")

    # Cleanup Bucket
    _api_post(f"/api/storage/buckets/{b_uid}?permanent=true", method="DELETE")
    print(f"    ✓ Cleaned up test bucket {b_uid}")

    print("[5] Testing Persistent Tunnel State & Auto-Resume...")
    record_tunnel_route("test-tunnel", "cloudflare", "testsite", "test.example.com", 8088)
    state = load_tunnel_state()
    assert state.get("active_tunnel") == "test-tunnel"
    assert "testsite" in state.get("routes", {})
    print("    ✓ Tunnel route recorded in persistent state")

    resume_res = resume_all_services()
    assert resume_res["agent_running"] is True, "Agent should be reported as running"
    print(f"    ✓ Auto-Resume executed: agent_running={resume_res['agent_running']}, active_tunnel={resume_res['active_tunnel']}")

    print("\n[ALL TESTS PASSED SUCCESSFULLY!]")

if __name__ == "__main__":
    test_interactive_features()
