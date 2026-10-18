"""Identity use-cases."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from app.kernel.security.device_keys import DeviceKeys
from app.kernel.security.tokens import TokenInvalidError, TokenService, TokenType
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.identity.api import UserCounts, UserPage, UserSummary
from app.modules.identity.domain import (
    USERNAME_PATTERN,
    AccountSuspendedError,
    CaptchaRequiredError,
    EmailTakenError,
    InvalidCredentialsError,
    InvalidUsernameError,
    LoginThrottledError,
    ProtectedAccountError,
    RefreshTokenInvalidError,
    RefreshTokenReuseError,
    Role,
    UnsupportedLocaleError,
    UsernameTakenError,
    UserNotFoundError,
    validate_password,
)
from app.modules.identity.guard import CaptchaVerifier, LoginAttemptGuard
from app.modules.identity.models import RefreshToken, User
from app.modules.identity.repository import RefreshTokenRepository, UserRepository
from app.shared_kernel.events import PasswordChanged, UserLoggedIn, UserRegistered, UserStatusChanged
from app.shared_kernel.locale import supported

PASSWORD_METHOD = "scrypt"  # noqa: S105 - hash algorithm name
_DUMMY_HASH = generate_password_hash("timing-equaliser-not-a-password", method=PASSWORD_METHOD)


def hash_password(password: str) -> str:
    return generate_password_hash(password, method=PASSWORD_METHOD)


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def to_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=bool(user.is_active),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        locale=user.locale,
    )


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip: str
    user_agent: str
    client_device_id: str | None
    language: str | None = None  # negotiated from Accept-Language (supported locales only)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user: User
    access_token: str
    access_expires_in: int
    refresh_token: str
    refresh_expires_in: int


class AuthService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        tokens: TokenService,
        guard: LoginAttemptGuard,
        captcha: CaptchaVerifier,
        device_keys: DeviceKeys,
        clock: Clock,
        refresh_ttl_s: int,
    ) -> None:
        self._uow = uow
        self._tokens = tokens
        self._guard = guard
        self._captcha = captcha
        self._device_keys = device_keys
        self._clock = clock
        self._refresh_ttl = refresh_ttl_s

    # ── Registration ───────────────────────────────────────────────────────
    def register(self, *, username: str, email: str | None, password: str, locale: str | None = None) -> User:
        username = username.strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise InvalidUsernameError("Username must be 3-64 characters: letters, digits, '_', '.', '-'")
        validate_password(password, username=username)
        with self._uow() as uow:
            users = UserRepository(uow.session)
            if users.username_exists(username):
                raise UsernameTakenError("Username is already taken")
            if email and users.email_exists(email):
                raise EmailTakenError("Email is already registered")
            user = users.add(
                User(
                    username=username,
                    email=email.strip().lower() if email else None,
                    password_hash=hash_password(password),
                    role=Role.USER,
                    is_active=True,
                    token_version=1,
                    created_at=self._clock.now(),
                    locale=supported(locale),
                )
            )
            uow.outbox.add(
                UserRegistered(
                    user_id=user.id,
                    username=user.username,
                    email=user.email,
                    registered_at=self._clock.now().isoformat(),
                )
            )
        return user

    def username_available(self, username: str) -> bool:
        with self._uow() as uow:
            return USERNAME_PATTERN.fullmatch(username.strip()) is not None and not UserRepository(
                uow.session
            ).username_exists(username)

    def set_locale(self, *, user_id: int, locale: str) -> User:
        """The language the account's e-mails and interface use (shared by every device)."""
        value = supported(locale)
        if value is None:
            raise UnsupportedLocaleError(f"Unsupported language '{locale}'")
        with self._uow() as uow:
            user = UserRepository(uow.session).get(user_id)
            if user is None:
                raise UserNotFoundError("User not found")
            user.locale = value
            return user

    # ── Login ──────────────────────────────────────────────────────────────
    def login(self, *, username: str, password: str, captcha_token: str | None, client: ClientInfo) -> IssuedSession:
        delay = self._guard.required_delay(username)
        if delay:
            raise LoginThrottledError(delay)
        if self._guard.requires_captcha(username) and not self._captcha.verify(captcha_token, remote_ip=client.ip):
            raise CaptchaRequiredError("Captcha verification required")

        with self._uow() as uow:
            users = UserRepository(uow.session)
            user = users.by_username(username)
            valid = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)  # constant work
            if user is None or not valid:
                self._guard.record_failure(username)
                raise InvalidCredentialsError("Invalid username or password")
            if not user.is_active:
                raise AccountSuspendedError("Account is suspended")
            self._guard.record_success(username)
            if not user.password_hash.startswith(f"{PASSWORD_METHOD}:"):
                user.password_hash = hash_password(password)  # transparent re-hash of legacy pbkdf2 hashes
            user.last_login_at = self._clock.now()
            user.last_login_ip = client.ip[:45]
            if user.locale is None and client.language:
                user.locale = client.language  # accounts from before languages: adopt the browser's once
            session = self._issue(uow.session, user, client, family_id=str(uuid.uuid4()))
            uow.outbox.add(
                UserLoggedIn(
                    user_id=user.id,
                    client_device_id=self._device_keys.normalise_client_id(client.client_device_id),
                    user_agent=client.user_agent[:512],
                    ip=client.ip[:45],
                    occurred_at=self._clock.now().isoformat(),
                )
            )
        return session

    # ── Refresh (rotation + reuse detection) ───────────────────────────────
    def refresh(self, *, raw_refresh_token: str | None, client: ClientInfo) -> IssuedSession:
        if not raw_refresh_token:
            raise RefreshTokenInvalidError("Refresh token missing")
        failure: Exception | None = None
        issued: IssuedSession | None = None
        with self._uow() as uow:
            tokens = RefreshTokenRepository(uow.session)
            current = tokens.by_hash(_hash_refresh(raw_refresh_token), for_update=True)
            now = self._clock.now()
            if current is None:
                failure = RefreshTokenInvalidError("Unknown refresh token")
            elif current.revoked_at is not None or current.rotated_at is not None:
                tokens.revoke_family(current.family_id)  # committed below — reuse ⇒ kill the family
                failure = RefreshTokenReuseError("Refresh token reuse detected; session revoked")
            elif current.expires_at <= now:
                failure = RefreshTokenInvalidError("Refresh token expired")
            else:
                user = UserRepository(uow.session).get(current.user_id)
                if user is None or not user.is_active:
                    tokens.revoke_family(current.family_id)
                    failure = AccountSuspendedError("Account is suspended")
                else:
                    current.rotated_at = now
                    issued = self._issue(uow.session, user, client, family_id=current.family_id)
        if failure is not None:
            raise failure
        assert issued is not None
        return issued

    # ── Logout ─────────────────────────────────────────────────────────────
    def logout(self, *, raw_refresh_token: str | None) -> None:
        if not raw_refresh_token:
            return
        with self._uow() as uow:
            tokens = RefreshTokenRepository(uow.session)
            token = tokens.by_hash(_hash_refresh(raw_refresh_token))
            if token is not None:
                tokens.revoke_family(token.family_id)

    def logout_everywhere(self, *, user_id: int) -> None:
        with self._uow() as uow:
            user = UserRepository(uow.session).get(user_id)
            if user is None:
                raise UserNotFoundError()
            user.token_version += 1  # invalidates every outstanding access token
            RefreshTokenRepository(uow.session).revoke_user(user_id)

    def change_password(self, *, user_id: int, current: str, new: str, client: ClientInfo) -> IssuedSession:
        with self._uow() as uow:
            user = UserRepository(uow.session).get(user_id)
            if user is None:
                raise UserNotFoundError()
            if not check_password_hash(user.password_hash, current):
                raise InvalidCredentialsError("Current password is incorrect")
            validate_password(new, username=user.username)
            user.password_hash = hash_password(new)
            user.token_version += 1
            RefreshTokenRepository(uow.session).revoke_user(user_id)
            session = self._issue(uow.session, user, client, family_id=str(uuid.uuid4()))
            # Security notice to the owner rides on the outbox: committed atomically with the change.
            uow.outbox.add(PasswordChanged(user_id=user.id, method="change", occurred_at=self._clock.now().isoformat()))
        return session

    def revoke_device_sessions(self, *, user_id: int, device_key: str, session: Any) -> int:
        return RefreshTokenRepository(session).revoke_user(user_id, device_key=device_key)

    # ── internals ─────────────────────────────────────────────────────────
    def _issue(self, session: Any, user: User, client: ClientInfo, *, family_id: str) -> IssuedSession:
        raw = secrets.token_urlsafe(48)
        now = self._clock.now()
        RefreshTokenRepository(session).add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id,
                token_hash=_hash_refresh(raw),
                device_key=self._device_keys.key(user.id, client.client_device_id, client.user_agent),
                user_agent=client.user_agent[:255],
                ip=client.ip[:45],
                created_at=now,
                expires_at=now + timedelta(seconds=self._refresh_ttl),
            )
        )
        access = self._tokens.issue(sub=user.id, typ=TokenType.ACCESS, ver=user.token_version, role=user.role)
        return IssuedSession(
            user=user,
            access_token=access,
            access_expires_in=self._tokens.ttl(TokenType.ACCESS),
            refresh_token=raw,
            refresh_expires_in=self._refresh_ttl,
        )


class BearerAuthenticationBackend:
    """Kernel ``AuthenticationBackend``: stateless bearer access tokens.

    A token is accepted only if its type is ACCESS, the user still exists, is
    active (suspension is immediate — SEC-05) and the token version matches
    (password change / logout-everywhere revoke all access tokens)."""

    def __init__(self, tokens: TokenService, session_provider: Any) -> None:
        self._tokens = tokens
        self._session = session_provider

    def authenticate(self, req: Any) -> User | None:
        scheme, _, raw = (req.headers.get("Authorization") or "").partition(" ")
        if scheme.lower() != "bearer" or not raw:
            return None
        try:
            claims = self._tokens.verify(raw.strip(), expected=TokenType.ACCESS)
        except TokenInvalidError:
            return None
        if not claims.sub.isdigit():
            return None
        user = UserRepository(self._session()).get(int(claims.sub))
        if user is None or not user.is_active or user.token_version != claims.ver:
            return None
        return user


class UserDirectoryService:
    def __init__(self, session_provider: Any) -> None:
        self._session = session_provider

    def get(self, user_id: int) -> UserSummary | None:
        user = UserRepository(self._session()).get(user_id)
        return to_summary(user) if user else None

    def exists(self, user_id: int) -> bool:
        return UserRepository(self._session()).get(user_id) is not None


class IdentityAdminService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def list_users(self, *, cursor: int | None, limit: int, search: str | None) -> UserPage:
        limit = max(1, min(limit, 100))
        with self._uow() as uow:
            rows = UserRepository(uow.session).page(cursor=cursor, limit=limit + 1, search=search)
        has_next = len(rows) > limit
        rows = rows[:limit]
        return UserPage(items=[to_summary(u) for u in rows], next_cursor=rows[-1].id if has_next and rows else None)

    def set_active(self, *, user_id: int, active: bool, actor_id: int) -> UserSummary:
        with self._uow() as uow:
            user = UserRepository(uow.session).get(user_id)
            if user is None:
                raise UserNotFoundError("User not found")
            if user.id == actor_id and not active:
                raise ProtectedAccountError("You cannot suspend your own account")
            if user.role == Role.ADMIN and not active:
                raise ProtectedAccountError("Admin accounts cannot be suspended")
            if bool(user.is_active) != active:
                user.is_active = active
                if not active:
                    user.token_version += 1
                    RefreshTokenRepository(uow.session).revoke_user(user.id)
                uow.outbox.add(
                    UserStatusChanged(user_id=user.id, is_active=active, occurred_at=self._clock.now().isoformat())
                )
            summary = to_summary(user)
        return summary

    def counts(self) -> UserCounts:
        with self._uow() as uow:
            total, active, new = UserRepository(uow.session).counts(self._clock.now() - timedelta(hours=24))
        return UserCounts(total=total, active=active, new_last_24h=new)
