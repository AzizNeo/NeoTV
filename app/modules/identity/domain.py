"""Identity domain rules: roles, password policy, domain errors."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum

from app.kernel.security.permissions import WILDCARD


class Role:
    USER = "user"
    ADMIN = "admin"


#: Role → granted permissions. Only *declared* permissions are allowed
#: (validated at boot by ``post_boot.validate_roles``).
ROLE_PERMISSIONS: Mapping[str, frozenset[str]] = {
    Role.USER: frozenset(),
    Role.ADMIN: frozenset({WILDCARD}),
}


def role_grants(role: str, permission: str) -> bool:
    granted = ROLE_PERMISSIONS.get(role, frozenset())
    return WILDCARD in granted or permission in granted


# ── Account recovery ───────────────────────────────────────────────────────
class TokenPurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"  # noqa: S105 - purpose label, not a secret


#: Lifetimes of one-time links. Short for resets (account takeover window),
#: long enough for verification mails that sit in an inbox for a weekend.
TOKEN_TTL: Mapping[TokenPurpose, timedelta] = {
    TokenPurpose.RESET_PASSWORD: timedelta(minutes=30),
    TokenPurpose.VERIFY_EMAIL: timedelta(hours=48),
}
#: At most one mail per purpose and account in this window (mail-bombing guard).
TOKEN_COOLDOWN = timedelta(seconds=60)


# ── Errors ──────────────────────────────────────────────────────────────────
class IdentityError(Exception):
    def __init__(self, message: str = "", *, details: object = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.details = details


class InvalidCredentialsError(IdentityError):
    pass


class AccountSuspendedError(IdentityError):
    pass


class LoginThrottledError(IdentityError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            f"Too many failed attempts, retry in {retry_after}s", details={"retry_after_seconds": retry_after}
        )
        self.retry_after = retry_after


class CaptchaRequiredError(IdentityError):
    pass


class UsernameTakenError(IdentityError):
    pass


class InvalidUsernameError(IdentityError):
    pass


class EmailTakenError(IdentityError):
    pass


class WeakPasswordError(IdentityError):
    pass


class RefreshTokenInvalidError(IdentityError):
    pass


class RefreshTokenReuseError(IdentityError):
    """A rotated (already used) refresh token was presented → whole family revoked."""


class UserNotFoundError(IdentityError):
    pass


class CsrfHeaderMissingError(IdentityError):
    pass


class ProtectedAccountError(IdentityError):
    pass


# ── Password policy ─────────────────────────────────────────────────────────
_COMMON = frozenset(
    {
        "password",
        "password1",
        "password123",
        "1234567890",
        "12345678910",
        "qwertyuiop",
        "iloveyou123",
        "admin12345",
        "letmein123",
        "welcome123",
        "sifre12345",
        "parola1234",
    }
)
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def validate_password(password: str, *, username: str) -> None:
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"at most {MAX_PASSWORD_LENGTH} characters")
    if len(set(password)) < 4:
        problems.append("at least 4 distinct characters")
    if password.lower() in _COMMON:
        problems.append("not a common password")
    if username and username.lower() in password.lower():
        problems.append("must not contain the username")
    classes = sum(bool(re.search(pattern, password)) for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 2:
        problems.append("mix at least two of: lowercase, uppercase, digits, symbols")
    if problems:
        raise WeakPasswordError("Password does not meet the policy", details={"rules": problems})


class ActionTokenInvalidError(IdentityError):
    """Unknown, expired, used or superseded one-time link — deliberately one error (no oracle)."""


class EmailDeliveryUnavailableError(IdentityError):
    """The notifications module is disabled, so no mail can be sent."""


class EmailMissingError(IdentityError):
    pass


class EmailAlreadyVerifiedError(IdentityError):
    pass
