# Cyan Server — https://github.com/nadeemmhdm/cyan-server
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from security.dependencies import require_auth
from security.rate_limit import check_rate_limit, RateLimitExceeded
from authsvc import manager as authsvc

router = APIRouter(prefix="/api/authsvc", tags=["authsvc"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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


@router.put("/projects/{project_id}/policy")
def update_policy(project_id: str, req: UpdatePolicyRequest, _=Depends(require_auth)):
    try:
        return authsvc.update_project_policy(
            project_id, req.require_email_verification, req.password_min_length,
            req.max_login_attempts, req.lockout_minutes)
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
    try:
        return authsvc.verify_email_token(req.token)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))


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
    code: str   # the OTP or the link token — either works
    new_password: str


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request):
    try:
        check_rate_limit(_client_ip(request))
    except RateLimitExceeded:
        raise HTTPException(429, "Too many requests — try again shortly")
    try:
        return authsvc.reset_password(req.api_key, req.email, req.code, req.new_password)
    except authsvc.AuthSvcError as e:
        raise HTTPException(400, str(e))
