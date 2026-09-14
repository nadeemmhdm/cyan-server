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


def _latest_email_otp() -> str:
    raw = _CAPTURE_FILE.read_text()
    # A leading blank line before the headers makes email.message_from_string
    # treat the whole message as header-less body text (RFC5322: the first
    # blank line ends the headers — an *empty* header section still counts),
    # so get_body() silently returns None instead of finding the html part.
    last = raw.split("=====EMAIL=====")[-1].lstrip("\n")
    msg = email_lib.message_from_string(last, policy=policy.default)
    body = msg.get_body(preferencelist=("html",))
    assert body is not None, f"could not find an html body in the captured email:\n{last!r}"
    body = body.get_content()
    m = re.search(r"letter-spacing:4px\">(\d{6})<", body)
    assert m, f"no OTP found in latest email:\n{body}"
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
    assert {t["template_type"] for t in templates} == {"email_verify", "password_reset"}


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
    raw = _CAPTURE_FILE.read_text()
    last = raw.split("=====EMAIL=====")[-1]
    m = re.search(r'href="[^"]*token=([\w\-]+)"', last)
    assert m
    result = authsvc.verify_email_token(m.group(1))
    assert result["verified"] is True
    # A second use of the same token must fail — single use only.
    try:
        authsvc.verify_email_token(m.group(1))
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
    print("All tests passed.")
