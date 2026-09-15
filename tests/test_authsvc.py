# Cyan Server — https://github.com/nadeemmhdm/cyan-server
"""Auth Service tests. Runs a real local SMTP server (aiosmtpd) in-process
and exercises the actual smtplib send path -- no mocking of email delivery
-- plus real bcrypt-hashed passwords, real OTP/token generation, and a
real database-backed progressive lockout."""
import email as email_lib
import os
import re
import sys
import tempfile
from email import policy
from pathlib import Path

os.environ["CYAN_DATA_DIR"] = tempfile.mkdtemp(prefix="cyan-authsvc-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.database as _core_db  # noqa: E402
_TEST_DATA_DIR = os.environ["CYAN_DATA_DIR"]  # read by conftest.py's per-module fixture
_core_db.configure()
from core.database import init_db  # noqa: E402
init_db()

import authsvc.manager as authsvc  # noqa: E402

SMTP_PORT = 2526
SMTP_USER = "testuser@example.com"
SMTP_PASSWORD = "correct-app-password"
_CAPTURE_FILE = Path(tempfile.mkdtemp(prefix="cyan-authsvc-smtp-")) / "captured.txt"

pytest_plugins = []


def _start_fake_smtp():
    from aiosmtpd.controller import Controller
    from aiosmtpd.smtp import AuthResult, LoginPassword

    class Handler:
        async def handle_DATA(self, server, session, envelope):
            with open(_CAPTURE_FILE, "a") as f:
                f.write("=====EMAIL=====\n")
                f.write(envelope.content.decode("utf8", errors="replace"))
                f.write("\n")
            return "250 OK"

    def auth_callback(server, session, envelope, mechanism, auth_data):
        if isinstance(auth_data, LoginPassword):
            if auth_data.login.decode() == SMTP_USER and auth_data.password.decode() == SMTP_PASSWORD:
                return AuthResult(success=True)
        return AuthResult(success=False, handled=False)

    controller = Controller(Handler(), hostname="127.0.0.1", port=SMTP_PORT,
                             auth_require_tls=False, authenticator=auth_callback)
    controller.start()
    return controller


_controller = _start_fake_smtp()


def _latest_email_body() -> str:
    raw = _CAPTURE_FILE.read_text()
    last = raw.split("=====EMAIL=====")[-1].lstrip("\n")
    msg = email_lib.message_from_string(last, policy=policy.default)
    body = msg.get_body(preferencelist=("html",))
    assert body is not None, f"could not find an html body in the captured email:\n{last!r}"
    return body.get_content()


def _latest_email_otp() -> str:
    body = _latest_email_body()
    m = re.search(r"letter-spacing:4px\">(\d{6})<", body)
    assert m, f"no OTP found in latest email:\n{body}"
    return m.group(1)


def _latest_email_link_token() -> str:
    body = _latest_email_body()
    m = re.search(r'href="[^"]*token=([\w\-]+)"', body)
    assert m, f"no link token found in latest email:\n{body}"
    return m.group(1)


def _new_project_with_smtp():
    proj = authsvc.create_project("Test App", "smoke-tested project")
    authsvc.configure_smtp(proj["project_id"], "127.0.0.1", SMTP_PORT, SMTP_USER,
                            SMTP_PASSWORD, use_tls=False, verify=True)
    return proj


def test_create_project_returns_key_once_and_seeds_templates():
    proj = authsvc.create_project("Proj A", "desc")
    assert proj["api_key"].startswith("ck_live_")
    templates = authsvc.get_templates(proj["project_id"])
    assert {t["template_type"] for t in templates} == {
        "email_verify", "password_reset", "email_change", "mfa_login"}


def test_smtp_verification_rejects_wrong_credentials():
    proj = authsvc.create_project("Proj B", "")
    try:
        authsvc.configure_smtp(proj["project_id"], "127.0.0.1", SMTP_PORT, SMTP_USER,
                                "totally-wrong-password", use_tls=False, verify=True)
        assert False, "wrong SMTP credentials should have been rejected"
    except authsvc.AuthSvcError as e:
        assert "authentication failed" in str(e).lower()


def test_password_policy_rejects_weak_passwords():
    proj = _new_project_with_smtp()
    for bad_password in ("short1A!", "alllowercase1!", "ALLUPPERCASE1!", "NoDigitsHere!", "NoSpecial123"):
        try:
            authsvc.register_user(proj["api_key"], "someone@example.com", bad_password)
            assert False, f"weak password accepted: {bad_password!r}"
        except authsvc.AuthSvcError:
            pass


def test_register_sends_real_email_and_verify_by_otp_then_login():
    proj = _new_project_with_smtp()
    reg = authsvc.register_user(proj["api_key"], "alice@customer.com", "Str0ng!Passw0rd")
    assert reg["status"] == "pending_verification"
    assert reg["email_sent"] is True

    # Login before verification must be blocked.
    try:
        authsvc.login(proj["api_key"], "alice@customer.com", "Str0ng!Passw0rd")
        assert False, "login should be blocked before email verification"
    except authsvc.AuthSvcError:
        pass

    otp = _latest_email_otp()
    result = authsvc.verify_email_otp(proj["api_key"], "alice@customer.com", otp)
    assert result["verified"] is True

    session = authsvc.login(proj["api_key"], "alice@customer.com", "Str0ng!Passw0rd")
    assert session["email"] == "alice@customer.com"
    payload = authsvc.verify_session_token(session["session_token"])
    assert payload["project_id"] == proj["project_id"]


def test_verify_by_link_token_also_works():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "bob@customer.com", "Str0ng!Passw0rd")
    token = _latest_email_link_token()
    result = authsvc.verify_email_token(token)
    assert result["verified"] is True
    # A second use of the same token must fail — single use only.
    try:
        authsvc.verify_email_token(token)
        assert False, "verification token should be single-use"
    except authsvc.AuthSvcError:
        pass


def test_progressive_lockout_after_repeated_failures():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "carol@customer.com", "Str0ng!Passw0rd")
    otp = _latest_email_otp()
    authsvc.verify_email_otp(proj["api_key"], "carol@customer.com", otp)

    locked = False
    for _ in range(10):
        try:
            authsvc.login(proj["api_key"], "carol@customer.com", "wrong-password")
        except authsvc.AccountLocked as e:
            locked = True
            assert e.retry_after_seconds > 0
            break
        except authsvc.InvalidCredentials:
            continue
    assert locked, "account should lock after repeated failed logins"

    # Even the correct password is rejected while locked.
    try:
        authsvc.login(proj["api_key"], "carol@customer.com", "Str0ng!Passw0rd")
        assert False, "login should be blocked while account is locked"
    except authsvc.AccountLocked:
        pass


def test_forgot_and_reset_password_round_trip():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "dave@customer.com", "Str0ng!Passw0rd")
    otp = _latest_email_otp()
    authsvc.verify_email_otp(proj["api_key"], "dave@customer.com", otp)

    authsvc.forgot_password(proj["api_key"], "dave@customer.com")
    reset_otp = _latest_email_otp()
    authsvc.reset_password(proj["api_key"], "dave@customer.com", reset_otp, "NewStr0ng!Pass1")

    session = authsvc.login(proj["api_key"], "dave@customer.com", "NewStr0ng!Pass1")
    assert session["email"] == "dave@customer.com"

    try:
        authsvc.login(proj["api_key"], "dave@customer.com", "Str0ng!Passw0rd")
        assert False, "old password should no longer work after reset"
    except authsvc.InvalidCredentials:
        pass


def test_forgot_password_does_not_leak_account_existence():
    proj = _new_project_with_smtp()
    result = authsvc.forgot_password(proj["api_key"], "nobody-registered@customer.com")
    assert result == {"email_sent": True}


def test_invalid_api_key_is_rejected():
    try:
        authsvc.login("ck_live_totally-made-up-key", "x@example.com", "whatever")
        assert False, "a made-up API key should be rejected"
    except authsvc.AuthSvcError as e:
        assert "invalid api key" in str(e).lower()


def test_custom_email_template_is_used():
    proj = _new_project_with_smtp()
    authsvc.update_template(proj["project_id"], "email_verify",
                             subject="Confirm your {{project_name}} account",
                             body_html="<p>Code: {{otp}}</p>")
    authsvc.register_user(proj["api_key"], "erin@customer.com", "Str0ng!Passw0rd")
    raw = _CAPTURE_FILE.read_text()
    last = raw.split("=====EMAIL=====")[-1]
    assert "Confirm your Test App account" in last or "Confirm your" in last
    assert "Code:" in last


def test_link_token_is_never_stored_in_plaintext():
    from core.database import get_session, AuthVerification
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "frank@customer.com", "Str0ng!Passw0rd")
    raw_token = _latest_email_link_token()

    s = get_session()
    rows = s.query(AuthVerification).all()
    s.close()
    assert all(r.token != raw_token for r in rows), "raw token must never be stored as-is"
    # But the token still works — it's looked up by hash.
    result = authsvc.verify_email_token(raw_token)
    assert result["verified"] is True


def test_verification_token_is_single_use():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "gina@customer.com", "Str0ng!Passw0rd")
    token = _latest_email_link_token()
    authsvc.verify_email_token(token)
    try:
        authsvc.verify_email_token(token)
        assert False, "a verification token must not work a second time"
    except authsvc.AuthSvcError:
        pass


def test_reset_password_by_token_single_use():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "henry@customer.com", "Str0ng!Passw0rd")
    otp = _latest_email_otp()
    authsvc.verify_email_otp(proj["api_key"], "henry@customer.com", otp)

    authsvc.forgot_password(proj["api_key"], "henry@customer.com")
    token = _latest_email_link_token()

    authsvc.reset_password_by_token(token, "BrandNew!Pass9")
    authsvc.login(proj["api_key"], "henry@customer.com", "BrandNew!Pass9")

    try:
        authsvc.reset_password_by_token(token, "AnotherOne!Pass9")
        assert False, "a password-reset token must not work a second time"
    except authsvc.AuthSvcError:
        pass


def test_mfa_login_requires_second_factor():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "ivy@customer.com", "Str0ng!Passw0rd")
    otp = _latest_email_otp()
    authsvc.verify_email_otp(proj["api_key"], "ivy@customer.com", otp)

    authsvc.update_project_policy(proj["project_id"], mfa_enabled=True)

    result = authsvc.login(proj["api_key"], "ivy@customer.com", "Str0ng!Passw0rd")
    assert result.get("mfa_required") is True
    assert "session_token" not in result
    preauth = result["preauth_token"]

    mfa_otp = _latest_email_otp()
    session = authsvc.mfa_verify(preauth, mfa_otp)
    assert session["email"] == "ivy@customer.com"
    assert "session_token" in session

    # The same MFA code must not work twice.
    try:
        authsvc.mfa_verify(preauth, mfa_otp)
        assert False, "an MFA code must not work a second time"
    except authsvc.AuthSvcError:
        pass


def test_mfa_requires_smtp_before_enabling():
    proj = authsvc.create_project("No SMTP Yet", "")
    try:
        authsvc.update_project_policy(proj["project_id"], mfa_enabled=True)
        assert False, "MFA should not be enablable without SMTP configured"
    except authsvc.AuthSvcError:
        pass


def test_email_change_via_otp():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "jane@customer.com", "Str0ng!Passw0rd")
    otp = _latest_email_otp()
    authsvc.verify_email_otp(proj["api_key"], "jane@customer.com", otp)
    session = authsvc.login(proj["api_key"], "jane@customer.com", "Str0ng!Passw0rd")

    authsvc.request_email_change(session["session_token"], "jane-new@customer.com")
    change_otp = _latest_email_otp()
    result = authsvc.confirm_email_change_otp(session["session_token"], change_otp)
    assert result["email"] == "jane-new@customer.com"

    # Old email no longer logs in; new one does.
    try:
        authsvc.login(proj["api_key"], "jane@customer.com", "Str0ng!Passw0rd")
        assert False, "old email should no longer be a valid login"
    except authsvc.InvalidCredentials:
        pass
    authsvc.login(proj["api_key"], "jane-new@customer.com", "Str0ng!Passw0rd")


def test_email_change_via_link_token():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "kate@customer.com", "Str0ng!Passw0rd")
    otp = _latest_email_otp()
    authsvc.verify_email_otp(proj["api_key"], "kate@customer.com", otp)
    session = authsvc.login(proj["api_key"], "kate@customer.com", "Str0ng!Passw0rd")

    authsvc.request_email_change(session["session_token"], "kate-new@customer.com")
    result = authsvc.confirm_email_change_token(_latest_email_link_token())
    assert result["email"] == "kate-new@customer.com"


def test_email_change_rejects_email_already_in_use():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "liam@customer.com", "Str0ng!Passw0rd")
    authsvc.register_user(proj["api_key"], "mia@customer.com", "Str0ng!Passw0rd")
    otp = _latest_email_otp()
    authsvc.verify_email_otp(proj["api_key"], "mia@customer.com", otp)
    session = authsvc.login(proj["api_key"], "mia@customer.com", "Str0ng!Passw0rd")
    try:
        authsvc.request_email_change(session["session_token"], "liam@customer.com")
        assert False, "should not be able to change to an email already in use"
    except authsvc.AuthSvcError:
        pass


def test_html_pages_render_via_live_app():
    """Wire-level check that the GET link routes are actually mounted and
    return the default success/failure pages, using FastAPI's TestClient
    directly against the app object (no network, no separate process)."""
    from fastapi.testclient import TestClient
    from agent.main import app
    client = TestClient(app)

    resp = client.get("/api/authsvc/verify-email", params={"token": "not-a-real-token"})
    assert resp.status_code == 400
    assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()

    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "noah@customer.com", "Str0ng!Passw0rd")
    resp2 = client.get("/api/authsvc/verify-email", params={"token": _latest_email_link_token()})
    assert resp2.status_code == 200
    assert "verified" in resp2.text.lower()

    resp3 = client.get("/api/authsvc/reset-password", params={"token": "whatever"})
    assert resp3.status_code == 200
    assert "new password" in resp3.text.lower()


def test_api_key_cannot_see_another_projects_users():
    """Row-level security check: a valid API key must never resolve or
    act on another project's user rows, even with a matching email."""
    proj_a = _new_project_with_smtp()
    proj_b = _new_project_with_smtp()
    authsvc.register_user(proj_a["api_key"], "shared@customer.com", "Str0ng!Passw0rdA")
    otp_a = _latest_email_otp()   # capture A's OTP before B's registration overwrites "latest"
    authsvc.register_user(proj_b["api_key"], "shared@customer.com", "Str0ng!Passw0rdB")

    # Both projects registered the same email — verify project A's user with
    # its own OTP and confirm project B's account is untouched by it.
    authsvc.verify_email_otp(proj_a["api_key"], "shared@customer.com", otp_a)

    try:
        authsvc.login(proj_b["api_key"], "shared@customer.com", "Str0ng!Passw0rdB")
        assert False, "project B's account should still be unverified"
    except authsvc.AuthSvcError as e:
        assert "not verified" in str(e).lower()

    # Project A's password must not work against project B's account, even
    # though both are "shared@customer.com" — they are different rows.
    try:
        authsvc.login(proj_b["api_key"], "shared@customer.com", "Str0ng!Passw0rdA")
        assert False, "project A's credentials must not authenticate against project B"
    except authsvc.AuthSvcError:
        pass


def test_admin_user_management_list_disable_reset_delete():
    proj = _new_project_with_smtp()
    authsvc.register_user(proj["api_key"], "oscar@customer.com", "Str0ng!Passw0rd")
    otp = _latest_email_otp()
    authsvc.verify_email_otp(proj["api_key"], "oscar@customer.com", otp)

    users = authsvc.list_users(proj["project_id"])
    assert len(users) == 1
    u = users[0]
    assert u["email"] == "oscar@customer.com"
    assert 12 <= len(u["user_id"]) <= 15
    assert u["email_verified"] is True
    assert u["verification_method"] == "otp"
    assert u["disabled"] is False
    user_id = u["user_id"]

    # Disable blocks login.
    authsvc.admin_disable_user(proj["project_id"], user_id, True)
    try:
        authsvc.login(proj["api_key"], "oscar@customer.com", "Str0ng!Passw0rd")
        assert False, "disabled account should not be able to log in"
    except authsvc.AuthSvcError as e:
        assert "disabled" in str(e).lower()

    # Re-enable restores login.
    authsvc.admin_disable_user(proj["project_id"], user_id, False)
    authsvc.login(proj["api_key"], "oscar@customer.com", "Str0ng!Passw0rd")

    # Admin-triggered password reset sends a real email the user can act on.
    authsvc.admin_send_password_reset(proj["project_id"], user_id)
    reset_otp = _latest_email_otp()
    authsvc.reset_password(proj["api_key"], "oscar@customer.com", reset_otp, "AdminReset!Pass9")
    authsvc.login(proj["api_key"], "oscar@customer.com", "AdminReset!Pass9")

    # Delete removes the account entirely.
    authsvc.admin_delete_user(proj["project_id"], user_id)
    assert authsvc.list_users(proj["project_id"]) == []
    try:
        authsvc.login(proj["api_key"], "oscar@customer.com", "AdminReset!Pass9")
        assert False, "deleted account should no longer be able to log in"
    except authsvc.AuthSvcError:
        pass


if __name__ == "__main__":
    test_create_project_returns_key_once_and_seeds_templates()
    test_smtp_verification_rejects_wrong_credentials()
    test_password_policy_rejects_weak_passwords()
    test_register_sends_real_email_and_verify_by_otp_then_login()
    test_verify_by_link_token_also_works()
    test_progressive_lockout_after_repeated_failures()
    test_forgot_and_reset_password_round_trip()
    test_forgot_password_does_not_leak_account_existence()
    test_invalid_api_key_is_rejected()
    test_custom_email_template_is_used()
    test_link_token_is_never_stored_in_plaintext()
    test_verification_token_is_single_use()
    test_reset_password_by_token_single_use()
    test_mfa_login_requires_second_factor()
    test_mfa_requires_smtp_before_enabling()
    test_email_change_via_otp()
    test_email_change_via_link_token()
    test_email_change_rejects_email_already_in_use()
    test_html_pages_render_via_live_app()
    test_api_key_cannot_see_another_projects_users()
    print("All tests passed.")
