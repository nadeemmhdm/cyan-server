# Cyan Server — https://github.com/nadeemmhdm/cyan-server
from __future__ import annotations

import html as html_lib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from security.dependencies import require_auth
from security.rate_limit import check_rate_limit, RateLimitExceeded
from authsvc import manager as authsvc

router = APIRouter(prefix="/api/authsvc", tags=["authsvc"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Default landing pages for emailed links — a real browser GET click lands
# here, not on a JSON API response. Deliberately minimal and self-contained
# (no external assets) so they render correctly with zero network access.
# ---------------------------------------------------------------------------

def _page(title: str, heading: str, message: str, ok: bool) -> HTMLResponse:
    color = "#16a34a" if ok else "#dc2626"
    icon = "✓" if ok else "✕"
    body = f"""<!DOCTYPE html>
<!-- Cyan Server — https://github.com/nadeemmhdm/cyan-server -->
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_lib.escape(title)}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}}
.card{{background:#1e293b;border-radius:16px;padding:40px 32px;max-width:420px;text-align:center;
box-shadow:0 20px 40px rgba(0,0,0,.3)}}
.icon{{width:56px;height:56px;border-radius:50%;background:{color};color:#fff;font-size:28px;
display:flex;align-items:center;justify-content:center;margin:0 auto 20px}}
h1{{font-size:20px;margin:0 0 12px}}
p{{color:#94a3b8;line-height:1.5;margin:0}}
.brand{{margin-top:28px;font-size:12px;color:#475569}}
</style></head><body>
<div class="card">
<div class="icon">{icon}</div>
<h1>{html_lib.escape(heading)}</h1>
<p>{html_lib.escape(message)}</p>
<div class="brand">Cyan Server — Auth Service</div>
</div></body></html>"""
    return HTMLResponse(content=body, status_code=200 if ok else 400)


def _reset_form_page(token: str, error: str | None = None) -> HTMLResponse:
    error_html = f'<p style="color:#f87171;margin:0 0 16px">{html_lib.escape(error)}</p>' if error else ""
    body = f"""<!DOCTYPE html>
<!-- Cyan Server — https://github.com/nadeemmhdm/cyan-server -->
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reset your password</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}}
.card{{background:#1e293b;border-radius:16px;padding:40px 32px;max-width:380px;width:100%;
box-shadow:0 20px 40px rgba(0,0,0,.3)}}
h1{{font-size:20px;margin:0 0 20px;text-align:center}}
label{{font-size:13px;color:#94a3b8;display:block;margin-bottom:6px}}
input{{width:100%;box-sizing:border-box;padding:10px 12px;border-radius:8px;border:1px solid #334155;
background:#0f172a;color:#e2e8f0;font-size:14px;margin-bottom:16px}}
button{{width:100%;padding:11px;border-radius:8px;border:none;background:#0891b2;color:#fff;
font-size:14px;font-weight:600;cursor:pointer}}
button:hover{{background:#0e7490}}
.brand{{margin-top:20px;font-size:12px;color:#475569;text-align:center}}
</style></head><body>
<div class="card">
<h1>Set a new password</h1>
{error_html}
<form method="post" action="reset-password-form">
<input type="hidden" name="token" value="{html_lib.escape(token)}">
<label for="p">New password</label>
<input type="password" id="p" name="new_password" required minlength="8" autofocus>
<button type="submit">Reset password</button>
</form>
<div class="brand">Cyan Server — Auth Service</div>
</div></body></html>"""
    return HTMLResponse(content=body, status_code=200)


# ---------------------------------------------------------------------------
# Project management — admin-authenticated (this is Cyan Server's own
# dashboard/CLI managing projects, not an end user of one).
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""


@router.post("/projects")
def create_project(req: CreateProjectRequest, _=Depends(require_auth)):
    try:
        return authsvc.create_project(req.name, req.description)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


@router.get("/projects")
def list_projects(_=Depends(require_auth)):
    return authsvc.list_projects()


class UpdatePolicyRequest(BaseModel):
    require_email_verification: bool | None = None
    password_min_length: int | None = None
    max_login_attempts: int | None = None
    lockout_minutes: int | None = None
    mfa_enabled: bool | None = None


@router.put("/projects/{project_id}/policy")
def update_policy(project_id: str, req: UpdatePolicyRequest, _=Depends(require_auth)):
    try:
        return authsvc.update_project_policy(
            project_id, req.require_email_verification, req.password_min_length,
            req.max_login_attempts, req.lockout_minutes, req.mfa_enabled)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


class SMTPConfigRequest(BaseModel):
    host: str
    port: int
    email: str
    app_password: str
    use_tls: bool = True
    from_name: str = "Cyan Server"
    verify: bool = True   # real SMTP login check before saving — set False only for testing


@router.post("/projects/{project_id}/smtp")
def configure_smtp(project_id: str, req: SMTPConfigRequest, _=Depends(require_auth)):
    try:
        return authsvc.configure_smtp(project_id, req.host, req.port, req.email,
                                       req.app_password, req.use_tls, req.from_name, req.verify)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


@router.get("/projects/{project_id}/templates")
def get_templates(project_id: str, _=Depends(require_auth)):
    try:
        return authsvc.get_templates(project_id)
    except authsvc.AuthSvcError as e:
        raise HTTPException(404, str(e))


class UpdateTemplateRequest(BaseModel):
    subject: str
    body_html: str


@router.put("/projects/{project_id}/templates/{template_type}")
def update_template(project_id: str, template_type: str, req: UpdateTemplateRequest, _=Depends(require_auth)):
    try:
        return authsvc.update_template(project_id, template_type, req.subject, req.body_html)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# Public, API-key-scoped endpoints — called by whatever app/site is using
# this project's authentication, on behalf of ITS end users. No admin auth;
# the API key itself is the credential. Rate-limited per source IP.
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    api_key: str
    email: str
    password: str
    base_link_url: str | None = None


@router.post("/register")
def register(req: RegisterRequest, request: Request):
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many requests — try again shortly")
    try:
        return authsvc.register_user(req.api_key, req.email, req.password, req.base_link_url)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


class ResendRequest(BaseModel):
    api_key: str
    email: str
    base_link_url: str | None = None


@router.post("/resend-verification")
def resend_verification(req: ResendRequest, request: Request):
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many requests — try again shortly")
    try:
        return authsvc.resend_verification(req.api_key, req.email, req.base_link_url)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


class VerifyTokenRequest(BaseModel):
    token: str


@router.post("/verify-email")
def verify_email(req: VerifyTokenRequest):
    """JSON path — for apps handling the click themselves."""
    try:
        return authsvc.verify_email_token(req.token)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


@router.get("/verify-email", response_class=HTMLResponse)
def verify_email_page(token: str, request: Request):
    """The actual link a browser lands on when the user clicks 'verify my
    email' in the email. Single-use — a second click (or link prefetch by
    an email scanner) shows the failure page, not a second success."""
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        return _page("Too many requests", "Slow down", "Too many attempts — try again in a moment.", False)
    try:
        result = authsvc.verify_email_token(token)
        return _page("Email verified", "Email verified ✓",
                      f"{result['email']} is now verified. You can close this tab and sign in.", True)
    except authsvc.AuthSvcError as e:
        return _page("Verification failed", "Link invalid or expired", str(e), False)


class VerifyOtpRequest(BaseModel):
    api_key: str
    email: str
    otp: str


@router.post("/verify-otp")
def verify_otp(req: VerifyOtpRequest):
    try:
        return authsvc.verify_email_otp(req.api_key, req.email, req.otp)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


class LoginRequest(BaseModel):
    api_key: str
    email: str
    password: str


@router.post("/login")
def login(req: LoginRequest, request: Request):
    """Returns either {session_token, ...} or, when the project has MFA
    enabled, {mfa_required: true, preauth_token, ...} — call /mfa-verify
    with the emailed code and the preauth_token to get the real session."""
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many requests — try again shortly")
    try:
        return authsvc.login(req.api_key, req.email, req.password)
    except authsvc.AccountLocked as e:
        raise HTTPException(423, str(e))
    except authsvc.InvalidCredentials as e:
        raise HTTPException(401, str(e))
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


class MfaVerifyRequest(BaseModel):
    preauth_token: str
    otp: str


@router.post("/mfa-verify")
def mfa_verify(req: MfaVerifyRequest, request: Request):
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many requests — try again shortly")
    try:
        return authsvc.mfa_verify(req.preauth_token, req.otp)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


class ForgotPasswordRequest(BaseModel):
    api_key: str
    email: str
    base_link_url: str | None = None


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, request: Request):
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many requests — try again shortly")
    try:
        return authsvc.forgot_password(req.api_key, req.email, req.base_link_url)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


class ResetPasswordRequest(BaseModel):
    api_key: str
    email: str
    otp: str
    new_password: str


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request):
    """The OTP path, paired with api_key+email. For the emailed LINK, the
    browser instead lands on GET/POST /reset-password?token=... below —
    no API key travels in that email, the token alone is proof enough."""
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many requests — try again shortly")
    try:
        return authsvc.reset_password(req.api_key, req.email, req.otp, req.new_password)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(token: str, request: Request):
    """The link's landing page: a small form to enter a new password. No
    password is reset by a bare GET — resetting always requires the POST
    below, so link prefetching / scanners can't trigger an actual change."""
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        return _page("Too many requests", "Slow down", "Too many attempts — try again in a moment.", False)
    return _reset_form_page(token)


@router.post("/reset-password-form", response_class=HTMLResponse, include_in_schema=False)
async def reset_password_submit_form(request: Request):
    form = await request.form()
    token = form.get("token", "")
    new_password = form.get("new_password", "")
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        return _page("Too many requests", "Slow down", "Too many attempts — try again in a moment.", False)
    try:
        authsvc.reset_password_by_token(token, new_password)
        return _page("Password reset", "Password reset ✓",
                      "Your password has been changed. You can close this tab and sign in.", True)
    except authsvc.AuthSvcError as e:
        return _reset_form_page(token, error=str(e))


class EmailChangeRequest(BaseModel):
    session_token: str
    new_email: str
    base_link_url: str | None = None


@router.post("/email-change/request")
def email_change_request(req: EmailChangeRequest, request: Request):
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many requests — try again shortly")
    try:
        return authsvc.request_email_change(req.session_token, req.new_email, req.base_link_url)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


class EmailChangeConfirmOtpRequest(BaseModel):
    session_token: str
    otp: str


@router.post("/email-change/confirm-otp")
def email_change_confirm_otp(req: EmailChangeConfirmOtpRequest):
    try:
        return authsvc.confirm_email_change_otp(req.session_token, req.otp)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


@router.get("/confirm-email-change", response_class=HTMLResponse)
def confirm_email_change_page(token: str, request: Request):
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        return _page("Too many requests", "Slow down", "Too many attempts — try again in a moment.", False)
    try:
        result = authsvc.confirm_email_change_token(token)
        return _page("Email changed", "Email changed ✓",
                      f"Your login email is now {result['email']}. You can close this tab.", True)
    except authsvc.AuthSvcError as e:
        return _page("Confirmation failed", "Link invalid or expired", str(e), False)
