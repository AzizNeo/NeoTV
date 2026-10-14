from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.db import db
from app.kernel.manifest import ExtensionSpec, ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.security.auth import AuthenticationBackend
from app.kernel.security.device_keys import DeviceKeys
from app.kernel.security.tokens import TokenService
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.identity.api import IdentityAdmin, UserDirectory
from app.modules.identity.domain import (
    AccountSuspendedError,
    ActionTokenInvalidError,
    CaptchaRequiredError,
    CsrfHeaderMissingError,
    EmailAlreadyVerifiedError,
    EmailDeliveryUnavailableError,
    EmailMissingError,
    EmailTakenError,
    EmailUnchangedError,
    InvalidCredentialsError,
    InvalidUsernameError,
    LoginThrottledError,
    ProtectedAccountError,
    RefreshTokenInvalidError,
    RefreshTokenReuseError,
    UnsupportedLocaleError,
    UsernameTakenError,
    UserNotFoundError,
    WeakPasswordError,
)
from app.shared_kernel.events import DeviceRevoked, EmailChanged, NewDeviceSignedIn, PasswordChanged, UserRegistered


def _services(c: Any) -> None:
    from werkzeug.security import check_password_hash

    from app.modules.identity.guard import CaptchaVerifier, LoginAttemptGuard, NoCaptchaVerifier
    from app.modules.identity.notices import SecurityNotices
    from app.modules.identity.recovery import AccountRecoveryService
    from app.modules.identity.services import (
        AuthService,
        BearerAuthenticationBackend,
        IdentityAdminService,
        UserDirectoryService,
        hash_password,
    )

    c.register(LoginAttemptGuard, lambda c: LoginAttemptGuard(c.resolve("kernel.redis")))
    c.register(CaptchaVerifier, lambda _c: NoCaptchaVerifier())
    c.register(
        AuthService,
        lambda c: AuthService(
            uow=c.resolve(UnitOfWorkFactory),
            tokens=c.resolve(TokenService),
            guard=c.resolve(LoginAttemptGuard),
            captcha=c.resolve(CaptchaVerifier),
            device_keys=c.resolve(DeviceKeys),
            clock=c.resolve(Clock),
            refresh_ttl_s=c.resolve(Settings).refresh_token_ttl_s,
        ),
    )
    c.register(
        AuthenticationBackend, lambda c: BearerAuthenticationBackend(c.resolve(TokenService), lambda: db.session)
    )
    c.register(UserDirectory, lambda _c: UserDirectoryService(lambda: db.session))
    c.register(
        AccountRecoveryService,
        lambda c: AccountRecoveryService(
            uow=c.resolve(UnitOfWorkFactory),
            clock=c.resolve(Clock),
            mailer=lambda: c.resolve(CapabilityIndex).optional("notifications.email"),
            frontend_base_url=c.resolve(Settings).frontend_base_url,
            hash_password=hash_password,
            check_password=check_password_hash,
        ),
    )
    c.register(
        SecurityNotices,
        lambda c: SecurityNotices(mailer=lambda: c.resolve(CapabilityIndex).optional("notifications.email")),
    )
    c.register(IdentityAdmin, lambda c: IdentityAdminService(c.resolve(UnitOfWorkFactory), c.resolve(Clock)))


manifest = ModuleManifest(
    name="identity",
    version="2.0.0",
    description="Accounts, credentials, stateless access tokens, rotating refresh tokens, roles.",
    provides={
        "identity.authentication": AuthenticationBackend,
        "identity.users": UserDirectory,
        "identity.admin": IdentityAdmin,
    },
    optional_requires=frozenset({"notifications.email"}),
    models=("app.modules.identity.models",),
    services=_services,
    routes=(RouteSpec("app.modules.identity.http:blueprint", "/api/v1/auth"),),
    subscriptions=(
        SubscriptionSpec(
            DeviceRevoked.NAME, "identity.revoke_device_tokens", "app.modules.identity.handlers:on_device_revoked"
        ),
        SubscriptionSpec(
            UserRegistered.NAME, "identity.send_verification_mail", "app.modules.identity.handlers:on_user_registered"
        ),
        SubscriptionSpec(
            PasswordChanged.NAME,
            "identity.notify_password_changed",
            "app.modules.identity.handlers:on_password_changed",
        ),
        SubscriptionSpec(
            EmailChanged.NAME, "identity.notify_email_changed", "app.modules.identity.handlers:on_email_changed"
        ),
        SubscriptionSpec(
            NewDeviceSignedIn.NAME,
            "identity.notify_new_device",
            "app.modules.identity.handlers:on_new_device_signed_in",
        ),
    ),
    # Dropped automatically when the notifications module is disabled.
    extensions=(ExtensionSpec("notifications.templates", "app.modules.identity.emails:templates"),),
    error_map={
        InvalidCredentialsError: (401, "INVALID_CREDENTIALS"),
        AccountSuspendedError: (403, "ACCOUNT_SUSPENDED"),
        ProtectedAccountError: (403, "PROTECTED_ACCOUNT"),
        LoginThrottledError: (429, "LOGIN_THROTTLED"),
        CaptchaRequiredError: (428, "CAPTCHA_REQUIRED"),
        UsernameTakenError: (409, "USERNAME_TAKEN"),
        InvalidUsernameError: (422, "INVALID_USERNAME"),
        EmailTakenError: (409, "EMAIL_TAKEN"),
        WeakPasswordError: (422, "WEAK_PASSWORD"),
        RefreshTokenInvalidError: (401, "REFRESH_INVALID"),
        RefreshTokenReuseError: (401, "REFRESH_REUSED"),
        UserNotFoundError: (404, "USER_NOT_FOUND"),
        CsrfHeaderMissingError: (403, "CSRF_HEADER_MISSING"),
        ActionTokenInvalidError: (400, "ACTION_TOKEN_INVALID"),
        EmailDeliveryUnavailableError: (503, "EMAIL_DELIVERY_UNAVAILABLE"),
        EmailMissingError: (409, "EMAIL_MISSING"),
        EmailAlreadyVerifiedError: (409, "EMAIL_ALREADY_VERIFIED"),
        EmailUnchangedError: (422, "EMAIL_UNCHANGED"),
        UnsupportedLocaleError: (422, "UNSUPPORTED_LOCALE"),
    },
    cli=("app.modules.identity.cli:identity_cli",),
    post_boot="app.modules.identity.post_boot:validate_roles",
)
