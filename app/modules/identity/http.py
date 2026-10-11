"""Identity HTTP adapter: /api/v1/auth."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint, Response, request
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.responses import ok
from app.kernel.resilience.rate_limit import Rate, client_ip
from app.kernel.security.auth import current_user, set_principal
from app.kernel.settings import Settings
from app.modules.identity.domain import ROLE_PERMISSIONS, CsrfHeaderMissingError
from app.modules.identity.recovery import AccountRecoveryService
from app.modules.identity.services import AuthService, ClientInfo, IssuedSession

blueprint = Blueprint("identity", __name__)

REFRESH_COOKIE = "neotv_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"
CSRF_HEADER = "X-Requested-With"


# ── Schemas ──────────────────────────────────────────────────────────────────
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(_Strict):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr | None = None
    password: str = Field(min_length=1, max_length=128)


class LoginRequest(_Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    captcha_token: str | None = Field(default=None, max_length=4096)


class UsernameCheckRequest(_Strict):
    username: str = Field(min_length=1, max_length=64)


class ChangeEmailRequest(_Strict):
    new_email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(_Strict):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(_Strict):
    email: EmailStr


class ResetPasswordRequest(_Strict):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=1, max_length=128)


class VerifyEmailRequest(_Strict):
    token: str = Field(min_length=20, max_length=200)


class EmailChangeLinkRequest(_Strict):
    token: str = Field(min_length=20, max_length=200)


class MeResponse(BaseModel):
    id: int
    username: str
    email: str | None
    email_verified: bool
    role: str
    permissions: list[str]
    created_at: datetime


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: MeResponse


class AvailabilityResponse(BaseModel):
    available: bool


class RegisteredResponse(BaseModel):
    id: int
    username: str


# ── helpers ─────────────────────────────────────────────────────────────────
def _client() -> ClientInfo:
    return ClientInfo(
        ip=client_ip(),
        user_agent=request.headers.get("User-Agent", "")[:512],
        client_device_id=request.headers.get("X-Device-ID"),
    )


def _me(user: Any) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        role=user.role,
        permissions=sorted(ROLE_PERMISSIONS.get(user.role, frozenset())),
        created_at=user.created_at,
    )


def _session_response(session: IssuedSession, *, status: int = 200) -> Response:
    settings = resolve(Settings)
    payload = SessionResponse(
        access_token=session.access_token, expires_in=session.access_expires_in, user=_me(session.user)
    )
    response = ok(payload.model_dump(mode="json"), status=status)
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        max_age=session.refresh_expires_in,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="Strict",
        path=REFRESH_COOKIE_PATH,
    )
    return response


def _require_csrf_header() -> None:
    # Custom header ⇒ cross-site forms cannot send it and cross-origin JS must pass CORS preflight.
    if not request.headers.get(CSRF_HEADER):
        raise CsrfHeaderMissingError(f"{CSRF_HEADER} header required")


def _clear_cookie(response: Response) -> Response:
    settings = resolve(Settings)
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, secure=settings.secure_cookies, httponly=True, samesite="Strict"
    )
    return response


# ── Routes ──────────────────────────────────────────────────────────────────
@blueprint.post("/register")
@endpoint(
    auth="public",
    summary="Create an account",
    rate=Rate("auth.register", rps=1, burst=3, per="ip"),
    body=RegisterRequest,
    response=RegisteredResponse,
    status=201,
    errors=("USERNAME_TAKEN", "EMAIL_TAKEN", "WEAK_PASSWORD", "INVALID_USERNAME"),
)
def register(body: RegisterRequest) -> RegisteredResponse:
    user = resolve(AuthService).register(username=body.username, email=body.email, password=body.password)
    return RegisteredResponse(id=user.id, username=user.username)


@blueprint.post("/check-username")
@endpoint(
    auth="public",
    summary="Check username availability",
    rate=Rate("auth.check_username", rps=3, burst=10, per="ip"),
    body=UsernameCheckRequest,
    response=AvailabilityResponse,
)
def check_username(body: UsernameCheckRequest) -> AvailabilityResponse:
    return AvailabilityResponse(available=resolve(AuthService).username_available(body.username))


@blueprint.post("/login")
@endpoint(
    auth="public",
    summary="Log in; sets the httpOnly refresh cookie",
    rate=Rate("auth.login", rps=2, burst=5, per="ip"),
    body=LoginRequest,
    response=SessionResponse,
    errors=("INVALID_CREDENTIALS", "LOGIN_THROTTLED", "CAPTCHA_REQUIRED", "ACCOUNT_SUSPENDED"),
)
def login(body: LoginRequest) -> Response:
    session = resolve(AuthService).login(
        username=body.username, password=body.password, captcha_token=body.captcha_token, client=_client()
    )
    set_principal(session.user)
    return _session_response(session)


@blueprint.post("/refresh")
@endpoint(
    auth="public",
    summary="Rotate the refresh cookie and obtain a new access token",
    rate=Rate("auth.refresh", rps=1, burst=10, per="ip"),
    response=SessionResponse,
    errors=("REFRESH_INVALID", "REFRESH_REUSED", "CSRF_HEADER_MISSING"),
)
def refresh() -> Response:
    _require_csrf_header()
    session = resolve(AuthService).refresh(raw_refresh_token=request.cookies.get(REFRESH_COOKIE), client=_client())
    return _session_response(session)


@blueprint.post("/logout")
@endpoint(auth="public", summary="Revoke the current refresh-token family", errors=("CSRF_HEADER_MISSING",))
def logout() -> Response:
    _require_csrf_header()
    resolve(AuthService).logout(raw_refresh_token=request.cookies.get(REFRESH_COOKIE))
    return _clear_cookie(ok(None, message="Logged out"))


@blueprint.post("/logout-all")
@endpoint(summary="Revoke every session of the current user")
def logout_all() -> Response:
    resolve(AuthService).logout_everywhere(user_id=current_user.id)
    return _clear_cookie(ok(None, message="Logged out from all devices"))


@blueprint.get("/me")
@endpoint(summary="Current user", response=MeResponse)
def me() -> MeResponse:
    return _me(current_user)


@blueprint.post("/change-password")
@endpoint(
    summary="Change password (revokes all other sessions)",
    rate=Rate("auth.change_password", rps=0.2, burst=3),
    body=ChangePasswordRequest,
    response=SessionResponse,
    errors=("INVALID_CREDENTIALS", "WEAK_PASSWORD"),
)
def change_password(body: ChangePasswordRequest) -> Response:
    session = resolve(AuthService).change_password(
        user_id=current_user.id, current=body.current_password, new=body.new_password, client=_client()
    )
    return _session_response(session)


# ── Account recovery ─────────────────────────────────────────────────────────
@blueprint.post("/password/forgot")
@endpoint(
    auth="public",
    summary="Request a password-reset link (same answer whether or not the address exists)",
    rate=Rate("auth.password_forgot", rps=0.1, burst=3, per="ip"),
    body=ForgotPasswordRequest,
    status=202,
    errors=("EMAIL_DELIVERY_UNAVAILABLE",),
)
def forgot_password(body: ForgotPasswordRequest) -> Response:
    resolve(AccountRecoveryService).request_password_reset(email=str(body.email))
    return ok(None, status=202, message="If the address belongs to an account, a reset link is on its way.")


@blueprint.post("/password/reset")
@endpoint(
    auth="public",
    summary="Set a new password with a reset link (revokes every session)",
    rate=Rate("auth.password_reset", rps=0.2, burst=5, per="ip"),
    body=ResetPasswordRequest,
    errors=("ACTION_TOKEN_INVALID", "WEAK_PASSWORD"),
)
def reset_password(body: ResetPasswordRequest) -> Response:
    resolve(AccountRecoveryService).reset_password(raw_token=body.token, new_password=body.new_password)
    return _clear_cookie(ok(None, message="Password updated. Please sign in again."))


@blueprint.post("/email/verification")
@endpoint(
    summary="(Re)send the e-mail verification link to the current address",
    rate=Rate("auth.email_verification", rps=0.05, burst=2),
    status=202,
    errors=("EMAIL_MISSING", "EMAIL_ALREADY_VERIFIED", "EMAIL_DELIVERY_UNAVAILABLE"),
)
def send_email_verification() -> Response:
    resolve(AccountRecoveryService).request_email_verification(user_id=current_user.id)
    return ok(None, status=202, message="Verification link sent.")


@blueprint.post("/email/verify")
@endpoint(
    auth="public",
    summary="Confirm an e-mail address with a verification link",
    rate=Rate("auth.email_verify", rps=0.5, burst=5, per="ip"),
    body=VerifyEmailRequest,
    errors=("ACTION_TOKEN_INVALID",),
)
def verify_email(body: VerifyEmailRequest) -> Response:
    resolve(AccountRecoveryService).verify_email(raw_token=body.token)
    return ok(None, message="E-mail address verified.")


@blueprint.post("/email/change")
@endpoint(
    summary="Request an e-mail change: confirmation link to the new address, warning to the current one",
    rate=Rate("auth.email_change", rps=0.05, burst=5),
    body=ChangeEmailRequest,
    status=202,
    errors=("INVALID_CREDENTIALS", "EMAIL_UNCHANGED", "EMAIL_TAKEN", "EMAIL_DELIVERY_UNAVAILABLE"),
)
def request_email_change(body: ChangeEmailRequest) -> Response:
    resolve(AccountRecoveryService).request_email_change(
        user_id=current_user.id, password=body.password, new_email=str(body.new_email)
    )
    return ok(None, status=202, message="Confirmation link sent to the new address.")


@blueprint.post("/email/change/confirm")
@endpoint(
    auth="public",
    summary="Confirm an e-mail change with the link sent to the new address",
    rate=Rate("auth.email_change_confirm", rps=0.5, burst=5, per="ip"),
    body=EmailChangeLinkRequest,
    errors=("ACTION_TOKEN_INVALID", "EMAIL_TAKEN"),
)
def confirm_email_change(body: EmailChangeLinkRequest) -> Response:
    resolve(AccountRecoveryService).confirm_email_change(raw_token=body.token)
    return ok(None, message="E-mail address changed.")


@blueprint.post("/email/change/revert")
@endpoint(
    auth="public",
    summary="Undo an e-mail change from the old address (ends every session, mails a reset link)",
    rate=Rate("auth.email_change_revert", rps=0.2, burst=5, per="ip"),
    body=EmailChangeLinkRequest,
    errors=("ACTION_TOKEN_INVALID", "EMAIL_TAKEN"),
)
def revert_email_change(body: EmailChangeLinkRequest) -> Response:
    resolve(AccountRecoveryService).revert_email_change(raw_token=body.token)
    return _clear_cookie(ok(None, message="E-mail change undone. Every session was signed out; check your inbox."))
