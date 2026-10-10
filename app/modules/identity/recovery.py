"""Account recovery: e-mail verification and password reset via one-time links.

Security properties:
* the raw secret only exists in the mail (DB stores SHA-256; the link carries it
  in the URL *fragment*, which never reaches servers, logs or Referer headers);
* single use, short TTL, older links superseded by newer ones;
* ``request_password_reset`` answers identically whether or not the address
  exists (no account enumeration) and is cooled down per account;
* a reset revokes every access/refresh token and notifies the account owner.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from typing import Protocol

from app.kernel.time import Clock
from app.kernel.uow import UnitOfWork, UnitOfWorkFactory
from app.modules.identity.domain import (
    TOKEN_COOLDOWN,
    TOKEN_TTL,
    ActionTokenInvalidError,
    EmailAlreadyVerifiedError,
    EmailDeliveryUnavailableError,
    EmailMissingError,
    TokenPurpose,
    validate_password,
)
from app.modules.identity.emails import PASSWORD_CHANGED, PASSWORD_RESET, VERIFY_EMAIL
from app.modules.identity.models import ActionToken, User
from app.modules.identity.repository import ActionTokenRepository, RefreshTokenRepository, UserRepository

LINK_PATHS = {TokenPurpose.RESET_PASSWORD: "/reset-password", TokenPurpose.VERIFY_EMAIL: "/verify-email"}


class Mailer(Protocol):
    """Consumer-owned port for the optional ``notifications.email`` capability."""

    def queue(self, *, to: str, template: str, context: dict[str, str], dedupe_key: str | None = None) -> str: ...


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AccountRecoveryService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        clock: Clock,
        mailer: Callable[[], Mailer | None],
        frontend_base_url: str,
        hash_password: Callable[[str], str],
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._mailer = mailer
        self._base = frontend_base_url.rstrip("/")
        self._hash_password = hash_password

    # ── password reset ─────────────────────────────────────────────────────
    def request_password_reset(self, *, email: str) -> None:
        """Always returns normally (same answer for unknown addresses)."""
        mailer = self._require_mailer()
        with self._uow() as uow:
            user = UserRepository(uow.session).by_email(email)
            if user is None or not user.is_active or not user.email:
                return
            self._send_link(uow, mailer, user, TokenPurpose.RESET_PASSWORD, PASSWORD_RESET)

    def reset_password(self, *, raw_token: str, new_password: str) -> User:
        with self._uow() as uow:
            token, user = self._redeem(uow, raw_token, TokenPurpose.RESET_PASSWORD)
            validate_password(new_password, username=user.username)  # raises before anything is consumed
            now = self._clock.now()
            user.password_hash = self._hash_password(new_password)
            user.token_version += 1  # every outstanding access token dies
            RefreshTokenRepository(uow.session).revoke_user(user.id)
            ActionTokenRepository(uow.session).consume_open(user.id, TokenPurpose.RESET_PASSWORD, now)
            if user.email_verified_at is None and (user.email or "").lower() == token.email.lower():
                user.email_verified_at = now  # the link proved control of the inbox
            mailer = self._mailer()
            if mailer is not None and user.email:
                mailer.queue(to=user.email, template=PASSWORD_CHANGED, context={"username": user.username})
            return user

    # ── e-mail verification ────────────────────────────────────────────────
    def request_email_verification(self, *, user_id: int) -> None:
        mailer = self._require_mailer()
        with self._uow() as uow:
            user = UserRepository(uow.session).get(user_id)
            if user is None or not user.email:
                raise EmailMissingError("No e-mail address on this account")
            if user.email_verified_at is not None:
                raise EmailAlreadyVerifiedError("E-mail address is already verified")
            self._send_link(uow, mailer, user, TokenPurpose.VERIFY_EMAIL, VERIFY_EMAIL)

    def verify_email(self, *, raw_token: str) -> User:
        with self._uow() as uow:
            token, user = self._redeem(uow, raw_token, TokenPurpose.VERIFY_EMAIL)
            if (user.email or "").lower() != token.email.lower():
                raise ActionTokenInvalidError("Link is not valid for the current e-mail address")
            now = self._clock.now()
            user.email_verified_at = user.email_verified_at or now
            ActionTokenRepository(uow.session).consume_open(user.id, TokenPurpose.VERIFY_EMAIL, now)
            return user

    def send_verification_after_signup(self, uow: UnitOfWork, user_id: int) -> None:
        """Outbox consumer path: best effort, never fails registration."""
        mailer = self._mailer()
        user = UserRepository(uow.session).get(user_id)
        if mailer is None or user is None or not user.email or user.email_verified_at is not None:
            return
        self._send_link(uow, mailer, user, TokenPurpose.VERIFY_EMAIL, VERIFY_EMAIL)

    # ── internals ──────────────────────────────────────────────────────────
    def _require_mailer(self) -> Mailer:
        mailer = self._mailer()
        if mailer is None:
            raise EmailDeliveryUnavailableError("E-mail delivery is not enabled on this server")
        return mailer

    def _send_link(self, uow: UnitOfWork, mailer: Mailer, user: User, purpose: TokenPurpose, template: str) -> None:
        tokens = ActionTokenRepository(uow.session)
        now = self._clock.now()
        last = tokens.latest_created_at(user.id, purpose)
        if last is not None and now - last < TOKEN_COOLDOWN:
            return  # silently: a burst of requests yields one mail
        tokens.consume_open(user.id, purpose, now)  # only the newest link works
        raw = secrets.token_urlsafe(32)
        ttl = TOKEN_TTL[purpose]
        tokens.add(
            ActionToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=_digest(raw),
                email=user.email,
                created_at=now,
                expires_at=now + ttl,
            )
        )
        context = {"username": user.username, "link": f"{self._base}{LINK_PATHS[purpose]}#token={raw}"}
        if purpose is TokenPurpose.RESET_PASSWORD:
            context["minutes"] = str(int(ttl.total_seconds() // 60))
        else:
            context["hours"] = str(int(ttl.total_seconds() // 3600))
        mailer.queue(to=user.email or "", template=template, context=context)

    def _redeem(self, uow: UnitOfWork, raw_token: str, purpose: TokenPurpose) -> tuple[ActionToken, User]:
        token = ActionTokenRepository(uow.session).by_hash(_digest(raw_token), purpose) if raw_token else None
        now = self._clock.now()
        if token is None or token.used_at is not None or token.expires_at <= now:
            raise ActionTokenInvalidError("This link is invalid or has expired")
        user = UserRepository(uow.session).get(token.user_id)
        if user is None or not user.is_active:
            raise ActionTokenInvalidError("This link is invalid or has expired")
        return token, user
