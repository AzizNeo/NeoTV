"""Use cases for Xtream app credentials: issue (shown once), list, revoke, authenticate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.kernel.http.profile_context import ProfileContext
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.identity.api import UserDirectory
from app.modules.profile.api import ProfileDirectory
from app.modules.xtream.domain import (
    LAST_USED_RESOLUTION_S,
    MAX_ACTIVE_PER_USER,
    PASSWORD_LENGTH,
    USERNAME_LENGTH,
    CredentialLimitReachedError,
    CredentialNotFoundError,
    KidsProfileManagementError,
    ProfileLockedError,
    ProfileNotOwnedError,
    XtreamPrincipal,
    digests_match,
    generate,
    is_well_formed,
    secret_digest,
)
from app.modules.xtream.models import XtreamCredential
from app.shared_kernel.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES

_USERNAME_ATTEMPTS = 3  # 31^10 names: a collision is already ~never; three tries make it a non-event


@dataclass(frozen=True, slots=True)
class CredentialView:
    id: int
    label: str
    username: str
    profile_id: int
    profile_name: str | None  # None: the profile is gone (the credential no longer works)
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    credential: CredentialView
    server_url: str
    password: str  # returned once, never stored in clear


class CredentialService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        *,
        key: bytes,
        users: UserDirectory,
        profiles: ProfileDirectory,
        server_url: str,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._key = key
        self._users = users
        self._profiles = profiles
        self._server_url = server_url.rstrip("/")
        # Same work for an unknown username as for a known one: no timing hint about which names exist.
        self._decoy = secret_digest(key, "x" * USERNAME_LENGTH, "x" * PASSWORD_LENGTH)

    @property
    def server_url(self) -> str:
        return self._server_url

    # ── Owner side (account settings) ─────────────────────────────────────

    def list(self, *, user_id: int, context: ProfileContext) -> list[CredentialView]:
        self._require_adult(context)
        with self._uow() as uow:
            rows = uow.session.execute(
                select(XtreamCredential)
                .where(XtreamCredential.user_id == user_id, XtreamCredential.revoked_at.is_(None))
                .order_by(XtreamCredential.created_at.desc(), XtreamCredential.id.desc())
            ).scalars()
            return [self._view(row) for row in rows]

    def issue(self, *, user_id: int, context: ProfileContext, profile_id: int, label: str) -> IssuedCredential:
        self._require_adult(context)
        profile = self._profiles.get(profile_id)
        if profile is None or profile.user_id != user_id:
            raise ProfileNotOwnedError("Profile not found")
        if profile.has_pin and profile.id != context.profile_id:
            # The PIN proves who may watch as that profile; it was entered only for the current one.
            raise ProfileLockedError("Select that profile (with its PIN) to create a credential for it")
        password = generate(PASSWORD_LENGTH)
        for attempt in range(_USERNAME_ATTEMPTS):
            username = generate(USERNAME_LENGTH)
            try:
                with self._uow() as uow:
                    active = uow.session.execute(
                        select(func.count(XtreamCredential.id)).where(
                            XtreamCredential.user_id == user_id, XtreamCredential.revoked_at.is_(None)
                        )
                    ).scalar_one()
                    if active >= MAX_ACTIVE_PER_USER:
                        raise CredentialLimitReachedError(f"At most {MAX_ACTIVE_PER_USER} active credentials")
                    row = XtreamCredential(
                        user_id=user_id,
                        profile_id=profile.id,
                        label=label,
                        username=username,
                        secret_hash=secret_digest(self._key, username, password),
                        created_at=self._clock.now(),
                    )
                    uow.session.add(row)
                    uow.session.flush()
                    view = self._view(row, profile_name=profile.name)
                return IssuedCredential(credential=view, server_url=self._server_url, password=password)
            except IntegrityError:
                if attempt == _USERNAME_ATTEMPTS - 1:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    def revoke(self, *, user_id: int, context: ProfileContext, credential_id: int) -> None:
        self._require_adult(context)
        with self._uow() as uow:
            row = uow.session.get(XtreamCredential, credential_id)
            if row is None or row.user_id != user_id or row.revoked_at is not None:
                raise CredentialNotFoundError("Credential not found")
            row.revoked_at = self._clock.now()

    # ── Event consumers (inside the handler's unit of work) ───────────────

    @staticmethod
    def revoke_for_user(session: Any, user_id: int, at: datetime) -> None:
        session.execute(
            update(XtreamCredential)
            .where(XtreamCredential.user_id == user_id, XtreamCredential.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    @staticmethod
    def revoke_for_profile(session: Any, profile_id: int, at: datetime) -> None:
        session.execute(
            update(XtreamCredential)
            .where(XtreamCredential.profile_id == profile_id, XtreamCredential.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    # ── App side (every Xtream request) ───────────────────────────────────

    def authenticate(self, username: str, password: str) -> XtreamPrincipal | None:
        """The principal for a valid, live credential — or ``None`` (one answer for every failure).

        Checked on every request rather than cached, so a revoked credential, a suspended account or a
        deleted profile stops working at once.
        """
        if not (is_well_formed(username, USERNAME_LENGTH) and is_well_formed(password, PASSWORD_LENGTH)):
            return None
        with self._uow() as uow:
            row = uow.session.execute(
                select(XtreamCredential).where(XtreamCredential.username == username)
            ).scalar_one_or_none()
            expected = row.secret_hash if row is not None else self._decoy
            if not digests_match(expected, secret_digest(self._key, username, password)) or row is None:
                return None
            if row.revoked_at is not None:
                return None
            user = self._users.get(row.user_id)
            profile = self._profiles.get(row.profile_id)
            if user is None or not user.is_active or profile is None or profile.user_id != row.user_id:
                return None
            now = self._clock.now()
            if row.last_used_at is None or now - row.last_used_at >= timedelta(seconds=LAST_USED_RESOLUTION_S):
                row.last_used_at = now
            return XtreamPrincipal(
                credential_id=row.id,
                username=row.username,
                user_id=row.user_id,
                profile_id=profile.id,
                is_kids=profile.is_kids,
                created_at=row.created_at,
                locale=user.locale if user.locale in SUPPORTED_LOCALES else DEFAULT_LOCALE,
            )

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _require_adult(context: ProfileContext) -> None:
        if context.is_kids:
            raise KidsProfileManagementError("App credentials are managed from an adult profile")

    def _view(self, row: XtreamCredential, *, profile_name: str | None = None) -> CredentialView:
        if profile_name is None:
            profile = self._profiles.get(row.profile_id)
            profile_name = profile.name if profile is not None and profile.user_id == row.user_id else None
        return CredentialView(
            id=row.id,
            label=row.label,
            username=row.username,
            profile_id=row.profile_id,
            profile_name=profile_name,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )
