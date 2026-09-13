"""
Automated test suite for v0.7.3 features:
1. Domain sanitization in Caddyfile & reverse proxy (white-screen fix).
2. Multi-file folder upload endpoint.
3. TOTP 2FA setup, verification, and login gate challenge.
"""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from core.database import Website, get_session, User
from web.reverse_proxy import render_caddyfile
from security.totp import generate_secret, get_totp_code, verify_totp

BASE_URL = "http://localhost:7331"


def test_domain_sanitization():
    print("Testing domain sanitization & Caddyfile rendering...")
    s = Website(id=999, name="sanitized-site", port=8080, status="running", domain="https://cyan.affogato.solutions/")
    caddy_content = render_caddyfile([s])
    assert "http://https://" not in caddy_content, "Duplicate http://https:// found in Caddyfile"
    assert "http://cyan.affogato.solutions, cyan.affogato.solutions" in caddy_content, "Domain not formatted cleanly"
    assert "reverse_proxy 127.0.0.1:8080" in caddy_content, "Upstream should be 127.0.0.1 to avoid IPv6 loopback issues"
    print("  [OK] Domain sanitization & Caddyfile upstream OK")


def test_totp_algorithm():
    print("Testing TOTP algorithm...")
    secret = generate_secret()
    code = get_totp_code(secret)
    assert len(code) == 6 and code.isdigit(), "Code must be 6 digits"
    assert verify_totp(secret, code), "Valid code must verify"
    bad_code = "999999" if code != "999999" else "888888"
    assert not verify_totp(secret, bad_code), "Invalid code must be rejected"
    print("  [OK] TOTP generation & verification OK")


def test_folder_upload_and_2fa_flow():
    print("Testing 2FA endpoints & folder upload via live agent API...")
    from security.auth import hash_password
    session = get_session()
    test_user = session.query(User).filter_by(username="testadmin").first()
    if not test_user:
        test_user = User(username="testadmin", password_hash=hash_password("testpass123"), role="admin")
        session.add(test_user)
        session.commit()
    else:
        test_user.password_hash = hash_password("testpass123")
        test_user.totp_enabled = False
        test_user.totp_secret = None
        session.commit()
    session.close()

    # 1. Login to get token
    r = httpx.post(f"{BASE_URL}/api/auth/login", json={"username": "testadmin", "password": "testpass123"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check 2FA initial status
    r = httpx.get(f"{BASE_URL}/api/auth/2fa/status", headers=headers)
    assert r.status_code == 200
    assert "enabled" in r.json()

    # 3. Setup 2FA
    r = httpx.post(f"{BASE_URL}/api/auth/2fa/setup", headers=headers)
    assert r.status_code == 200
    setup_data = r.json()
    secret = setup_data["secret"]
    assert "otpauth_url" in setup_data

    # 4. Enable 2FA using valid code
    code = get_totp_code(secret)
    r = httpx.post(f"{BASE_URL}/api/auth/2fa/enable", headers=headers, json={"code": code})
    assert r.status_code == 200, f"Enable failed: {r.text}"

    # 5. Check status is now enabled
    r = httpx.get(f"{BASE_URL}/api/auth/2fa/status", headers=headers)
    assert r.status_code == 200 and r.json()["enabled"] is True

    # 6. Test login without 2FA code -> should return require_2fa
    r = httpx.post(f"{BASE_URL}/api/auth/login", json={"username": "testadmin", "password": "testpass123"})
    assert r.status_code == 200
    assert r.json().get("require_2fa") is True, "Login did not prompt for 2FA"

    # 7. Test login with bad 2FA code -> should fail 401
    r = httpx.post(f"{BASE_URL}/api/auth/login", json={"username": "testadmin", "password": "testpass123", "totp_code": "000000"})
    assert r.status_code == 401

    # 8. Test login with correct 2FA code -> should succeed and issue token
    good_code = get_totp_code(secret)
    r = httpx.post(f"{BASE_URL}/api/auth/login", json={"username": "testadmin", "password": "testpass123", "totp_code": good_code})
    assert r.status_code == 200
    new_token = r.json()["access_token"]
    new_headers = {"Authorization": f"Bearer {new_token}"}

    # 9. Test folder upload on a test site
    # Create test site first
    httpx.post(f"{BASE_URL}/api/web", headers=new_headers, json={
        "name": "test-folder-site",
        "site_type": "static",
        "source_type": "folder",
        "source": "./sites/test-folder-site",
        "port": 9123,
    })

    # Upload multiple files with nested paths
    files = [
        ("files", ("index.html", b"<h1>Hello from folder upload</h1>", "text/html")),
        ("files", ("sub/app.js", b"console.log('nested app');", "application/javascript")),
    ]
    paths = json.dumps(["my-project/index.html", "my-project/sub/app.js"])
    r = httpx.post(f"{BASE_URL}/api/web/test-folder-site/files/upload-folder", headers=new_headers, files=files, data={"paths": paths})
    assert r.status_code == 200, f"Folder upload failed: {r.text}"
    assert r.json()["files_count"] == 2

    # Verify files were placed correctly
    r = httpx.get(f"{BASE_URL}/api/web/test-folder-site/files", headers=new_headers)
    assert r.status_code == 200
    file_names = [e["name"] for e in r.json()["entries"]]
    assert "index.html" in file_names

    # Clean up test site
    httpx.delete(f"{BASE_URL}/api/web/test-folder-site?permanent=true", headers=new_headers)

    # 10. Disable 2FA to return account to baseline
    r = httpx.post(f"{BASE_URL}/api/auth/2fa/disable", headers=new_headers, json={"password": "testpass123"})
    assert r.status_code == 200
    r = httpx.get(f"{BASE_URL}/api/auth/2fa/status", headers=new_headers)
    assert r.status_code == 200 and r.json()["enabled"] is False

    print("  [OK] Full 2FA lifecycle & multi-file folder upload verified successfully!")


if __name__ == "__main__":
    test_domain_sanitization()
    test_totp_algorithm()
    test_folder_upload_and_2fa_flow()
    print("\nALL TESTS PASSED SUCCESSFULLY!")
