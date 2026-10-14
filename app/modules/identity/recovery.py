"""Account recovery: e-mail verification and password reset via one-time links.

Security properties:
* the raw secret only exists in the mail (DB stores SHA-256; the link carries it
  in the URL *fragment*, which never reaches servers, logs or Referer headers);
* single use, short TTL, older links superseded by newer ones;
* ``request_password_reset`` answers identically whether or not the address
  exists (no account enumeration) and is cooled down per account;
* a reset revokes every access/refresh token and notifies the account owner;
* an e-mail change needs the current password, is confirmed from the *new*
  inbox, kills every open link (incl. resets sent to the old inbox) and gives
  the *old* inbox a 7-day undo link that also ends every session.
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
    EmailTakenError,
    EmailUnchangedError,
    InvalidCredentialsError,
    TokenPurpose,
    mask_email,
    validate_password,
)
from app.modules.identity.emails import (
    EMAIL_CHANGE_CONFIRM,
    EMAIL_CHANGE_REQUESTED,
    EMAIL_CHANGED,
    PASSWORD_RESET,
    VERIFY_EMAIL,
)
from app.modules.identity.models import ActionToken, User
from app.modules.identity.repository import ActionTokenRepository, RefreshTokenRepository, UserRepository
from app.shared_kernel.events import EmailChanged, PasswordChanged

#: Purposes that survive "burn every open link": undo links of e-mail changes.
_UNDO = frozenset({TokenPurpose.REVERT_EMAIL.value})

LINK_PATHS = {
    TokenPurpose.RESET_PASSWORD: "/reset-password",
    TokenPurpose.VERIFY_EMAIL: "/verify-email",
    TokenPurpose.CHANGE_EMAIL: "/confirm-email-change",
    TokenPurpose.REVERT_EMAIL: "/revert-email-change",
}


class Mailer(Protocol):
    """Consumer-owned port for the optional ``notifications.email`` capability."""

    def queue(
        self,
        *,
        to: str,
        template: str,
        context: dict[str, str],
        dedupe_key: str | None = None,
        locale: str | None = None,
    ) -> str: ...


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
        check_password: Callable[[str, str], bool],
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._mailer = mailer
        self._base = frontend_base_url.rstrip("/")
        self._hash_password = hash_password
        self._check_password = check_password

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
            uow.outbox.add(PasswordChanged(user_id=user.id, method="reset", occurred_at=now.isoformat()))
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

    # ── e-mail change ──────────────────────────────────────────────────────
    def request_email_change(self, *, user_id: int, password: str, new_email: str) -> None:
        """Mail a confirmation link to ``new_email``; warn the current address. Nothing changes yet."""
        mailer = self._require_mailer()
        address = new_email.strip().lower()
        with self._uow() as uow:
            users = UserRepository(uow.session)
            user = users.get(user_id)
            if user is None or not self._check_password(user.password_hash, password):
                raise InvalidCredentialsError("Current password is incorrect")
            if (user.email or "").lower() == address:
                raise EmailUnchangedError("This is already the account's e-mail address")
            if users.email_exists(address):
                raise EmailTakenError("Email is already registered")
            sent = self._send_link(uow, mailer, user, TokenPurpose.CHANGE_EMAIL, EMAIL_CHANGE_CONFIRM, to=address)
            if sent and user.email:
                mailer.queue(
                    to=user.email,
                    template=EMAIL_CHANGE_REQUESTED,
                    context={"username": user.username, "new_email": mask_email(address)},
                    locale=user.locale,
                )

    def confirm_email_change(self, *, raw_token: str) -> User:
        with self._uow() as uow:
            token, user = self._redeem(uow, raw_token, TokenPurpose.CHANGE_EMAIL)
            owner = UserRepository(uow.session).by_email(token.email)
            if owner is not None and owner.id != user.id:
                raise EmailTakenError("Email is already registered")  # taken while the link sat in the inbox
            now = self._clock.now()
            old = user.email
            user.email = token.email
            user.email_verified_at = now  # the link proved control of the new inbox
            # Every open link dies (incl. resets sent to the old inbox) — except undo links of earlier changes:
            # an attacker chaining two changes must not be able to cancel the real owner's undo.
            ActionTokenRepository(uow.session).consume_all_open(user.id, now, keep=_UNDO)
            uow.outbox.add(
                EmailChanged(user_id=user.id, old_email=old, new_email=token.email, occurred_at=now.isoformat())
            )
            return user

    def notify_email_changed(self, uow: UnitOfWork, event: EmailChanged) -> None:
        """Outbox consumer: tell the *old* inbox and hand it a 7-day undo link."""
        mailer = self._mailer()
        user = UserRepository(uow.session).get(event.user_id)
        if mailer is None or user is None or not event.old_email:
            return
        self._send_link(
            uow,
            mailer,
            user,
            TokenPurpose.REVERT_EMAIL,
            EMAIL_CHANGED,
            to=event.old_email,
            extra={"new_email": mask_email(event.new_email)},
            cooldown=False,  # a security notice must never be swallowed by the burst guard
            supersede=False,  # each old inbox keeps its own undo link (see confirm_email_change)
        )

    def revert_email_change(self, *, raw_token: str) -> User:
        """Undo a change from the old inbox: address back, every session ends (a takeover is assumed)."""
        with self._uow() as uow:
            token, user = self._redeem(uow, raw_token, TokenPurpose.REVERT_EMAIL)
            owner = UserRepository(uow.session).by_email(token.email)
            if owner is not None and owner.id != user.id:
                raise EmailTakenError("Email is already registered")
            now = self._clock.now()
            user.email = token.email
            user.email_verified_at = now
            user.token_version += 1
            RefreshTokenRepository(uow.session).revoke_user(user.id)
            tokens = ActionTokenRepository(uow.session)
            tokens.consume_all_open(user.id, now, keep=_UNDO)
            # The older address in a chain wins: undo links issued after this one (to later addresses) die.
            tokens.consume_open_since(user.id, TokenPurpose.REVERT_EMAIL, token.created_at, now)
            # Whoever changed the address knows the password: hand the owner a reset link right away.
            mailer = self._mailer()
            if mailer is not None:
                self._send_link(uow, mailer, user, TokenPurpose.RESET_PASSWORD, PASSWORD_RESET, cooldown=False)
            return user

    # ── internals ──────────────────────────────────────────────────────────
    def _require_mailer(self) -> Mailer:
        mailer = self._mailer()
        if mailer is None:
            raise EmailDeliveryUnavailableError("E-mail delivery is not enabled on this server")
        return mailer

    def _send_link(
        self,
        uow: UnitOfWork,
        mailer: Mailer,
        user: User,
        purpose: TokenPurpose,
        template: str,
        *,
        to: str | None = None,
        extra: dict[str, str] | None = None,
        cooldown: bool = True,
        supersede: bool = True,
    ) -> bool:
        """Issue the one-time link for ``purpose`` and mail it to ``to`` (default: the account's address).

        The token pins the address it was sent to. Returns ``False`` when the burst guard swallowed the request.
        """
        address = to or user.email or ""
        tokens = ActionTokenRepository(uow.session)
        now = self._clock.now()
        last = tokens.latest_created_at(user.id, purpose)
        if cooldown and last is not None and now - last < TOKEN_COOLDOWN:
            return False  # silently: a burst of requests yields one mail
        if supersede:
            tokens.consume_open(user.id, purpose, now)  # only the newest link works
        raw = secrets.token_urlsafe(32)
        ttl = TOKEN_TTL[purpose]
        tokens.add(
            ActionToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=_digest(raw),
                email=address,
                created_at=now,
                expires_at=now + ttl,
            )
        )
        context = {"username": user.username, "link": f"{self._base}{LINK_PATHS[purpose]}#token={raw}", **(extra or {})}
        if purpose is TokenPurpose.RESET_PASSWORD:
            context["minutes"] = str(int(ttl.total_seconds() // 60))
        elif purpose is TokenPurpose.REVERT_EMAIL:
            context["days"] = str(ttl.days)
        else:
            context["hours"] = str(int(ttl.total_seconds() // 3600))
        mailer.queue(to=address, template=template, context=context, locale=user.locale)
        return True

    def _redeem(self, uow: UnitOfWork, raw_token: str, purpose: TokenPurpose) -> tuple[ActionToken, User]:
        token = ActionTokenRepository(uow.session).by_hash(_digest(raw_token), purpose) if raw_token else None
        now = self._clock.now()
        if token is None or token.used_at is not None or token.expires_at <= now:
            raise ActionTokenInvalidError("This link is invalid or has expired")
        user = UserRepository(uow.session).get(token.user_id)
        if user is None or not user.is_active:
            raise ActionTokenInvalidError("This link is invalid or has expired")
        return token, user
