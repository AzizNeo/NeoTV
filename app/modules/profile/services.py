"""Profile use-cases and the kernel ``ProfileContextResolver`` implementation."""

from __future__ import annotations

import re
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.kernel.capabilities import CapabilityIndex
from app.kernel.db import dialect_insert
from app.kernel.http.errors import ApiError
from app.kernel.http.profile_context import ProfileContext
from app.kernel.security.tokens import TokenInvalidError, TokenService, TokenType
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.profile.api import ProfileSummary
from app.modules.profile.models import Profile
from app.shared_kernel.events import ProfileDeleted

_PIN = re.compile(r"^\d{4,8}$")
DEFAULT_PROFILE_NAME = "Ana Profil"
DEFAULT_MAX_PROFILES = 5
_INCR_WITH_TTL = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


class ProfileError(Exception):
    pass


class ProfileNotFoundError(ProfileError):
    pass


class ProfileLimitReachedError(ProfileError):
    pass


class ProfileNameTakenError(ProfileError):
    pass


class DefaultProfileProtectedError(ProfileError):
    pass


class PinRequiredError(ProfileError):
    pass


class PinInvalidError(ProfileError):
    pass


class PinFormatError(ProfileError):
    pass


class PinLockedError(ProfileError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many wrong PINs, retry in {retry_after}s")
        self.details = {"retry_after_seconds": retry_after}


class _EntitlementsLike(Protocol):  # consumer-owned port for the optional billing capability
    def for_user(self, user_id: int) -> Any: ...


def to_summary(profile: Profile) -> ProfileSummary:
    return ProfileSummary(
        id=profile.id,
        user_id=profile.user_id,
        name=profile.name,
        avatar=profile.avatar,
        is_kids=bool(profile.is_kids),
        is_default=bool(profile.is_default),
        has_pin=profile.pin_hash is not None,
    )


class ProfileRepository:
    def __init__(self, session: Any) -> None:
        self._s = session

    def get(self, profile_id: int) -> Profile | None:
        return self._s.get(Profile, profile_id)

    def for_user(self, user_id: int) -> list[Profile]:
        return list(
            self._s.execute(
                select(Profile).where(Profile.user_id == user_id).order_by(Profile.is_default.desc(), Profile.id)
            ).scalars()
        )

    def count_for_user(self, user_id: int) -> int:
        return int(self._s.execute(select(func.count(Profile.id)).where(Profile.user_id == user_id)).scalar_one())

    def default_for(self, user_id: int) -> Profile | None:
        return self._s.execute(
            select(Profile).where(Profile.user_id == user_id, Profile.is_default.is_(True))
        ).scalar_one_or_none()

    def ensure_default(self, user_id: int, now: Any) -> Profile:
        """Race-free get-or-create (partial unique index ux_profiles_user_default)."""
        existing = self.default_for(user_id)
        if existing is not None:
            return existing
        stmt = (
            dialect_insert(self._s, Profile.__table__)
            .values(
                user_id=user_id,
                name=DEFAULT_PROFILE_NAME,
                avatar="default",
                is_kids=False,
                is_default=True,
                created_at=now,
            )
            .on_conflict_do_nothing()
        )
        self._s.execute(stmt)
        created = self.default_for(user_id)
        assert created is not None
        return created


class ProfileService:
    MAX_PIN_ATTEMPTS = 5
    PIN_LOCK_SECONDS = 900

    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        tokens: TokenService,
        redis: Any,
        clock: Clock,
        capabilities: CapabilityIndex,
    ) -> None:
        self._uow = uow
        self._tokens = tokens
        self._redis = redis
        self._clock = clock
        self._capabilities = capabilities
        self._incr = redis.register_script(_INCR_WITH_TTL)

    # ── queries ────────────────────────────────────────────────────────────
    def list(self, user_id: int) -> list[ProfileSummary]:
        with self._uow() as uow:
            repo = ProfileRepository(uow.session)
            repo.ensure_default(user_id, self._clock.now())
            return [to_summary(p) for p in repo.for_user(user_id)]

    def get_owned(self, user_id: int, profile_id: int) -> ProfileSummary:
        with self._uow() as uow:
            return to_summary(self._owned(ProfileRepository(uow.session), user_id, profile_id))

    def default_for(self, user_id: int) -> ProfileSummary:
        with self._uow() as uow:
            return to_summary(ProfileRepository(uow.session).ensure_default(user_id, self._clock.now()))

    # ── commands ───────────────────────────────────────────────────────────
    def create(self, *, user_id: int, name: str, avatar: str, is_kids: bool) -> ProfileSummary:
        with self._uow() as uow:
            repo = ProfileRepository(uow.session)
            repo.ensure_default(user_id, self._clock.now())
            if repo.count_for_user(user_id) >= self._max_profiles(user_id):
                raise ProfileLimitReachedError("Your plan does not allow more profiles")
            profile = Profile(
                user_id=user_id,
                name=name,
                avatar=avatar,
                is_kids=is_kids,
                is_default=False,
                created_at=self._clock.now(),
            )
            uow.session.add(profile)
            try:
                uow.session.flush([profile])
            except IntegrityError as exc:
                raise ProfileNameTakenError("A profile with this name already exists") from exc
            summary = to_summary(profile)
        return summary

    def update(
        self, *, user_id: int, profile_id: int, name: str | None, avatar: str | None, is_kids: bool | None
    ) -> ProfileSummary:
        with self._uow() as uow:
            profile = self._owned(ProfileRepository(uow.session), user_id, profile_id)
            if name is not None:
                profile.name = name
            if avatar is not None:
                profile.avatar = avatar
            if is_kids is not None:
                if profile.is_default and is_kids:
                    raise DefaultProfileProtectedError("The main profile cannot be a kids profile")
                profile.is_kids = is_kids
            try:
                uow.session.flush([profile])
            except IntegrityError as exc:
                raise ProfileNameTakenError("A profile with this name already exists") from exc
            summary = to_summary(profile)
        return summary

    def delete(self, *, user_id: int, profile_id: int) -> None:
        with self._uow() as uow:
            profile = self._owned(ProfileRepository(uow.session), user_id, profile_id)
            if profile.is_default:
                raise DefaultProfileProtectedError("The main profile cannot be deleted")
            uow.session.delete(profile)
            uow.outbox.add(
                ProfileDeleted(user_id=user_id, profile_id=profile_id, occurred_at=self._clock.now().isoformat())
            )

    def set_pin(self, *, user_id: int, profile_id: int, pin: str, current_pin: str | None) -> ProfileSummary:
        if not _PIN.fullmatch(pin):
            raise PinFormatError("PIN must be 4–8 digits")
        with self._uow() as uow:
            profile = self._owned(ProfileRepository(uow.session), user_id, profile_id)
            if profile.pin_hash:
                self._check_pin(profile, current_pin)
            profile.pin_hash = generate_password_hash(pin, method="scrypt")
            summary = to_summary(profile)
        return summary

    def clear_pin(self, *, user_id: int, profile_id: int, current_pin: str | None) -> ProfileSummary:
        with self._uow() as uow:
            profile = self._owned(ProfileRepository(uow.session), user_id, profile_id)
            if profile.pin_hash:
                self._check_pin(profile, current_pin)
            profile.pin_hash = None
            summary = to_summary(profile)
        return summary

    def select(
        self, *, user_id: int, token_version: int, profile_id: int, pin: str | None
    ) -> tuple[str, ProfileSummary]:
        with self._uow() as uow:
            profile = self._owned(ProfileRepository(uow.session), user_id, profile_id)
            if profile.pin_hash:
                self._check_pin(profile, pin)
            summary = to_summary(profile)
        token = self._tokens.issue(
            sub=user_id,
            typ=TokenType.PROFILE,
            ver=token_version,
            profile_id=summary.id,
            is_kids=summary.is_kids,
            name=summary.name,
        )
        return token, summary

    # ── internals ─────────────────────────────────────────────────────────
    @staticmethod
    def _owned(repo: ProfileRepository, user_id: int, profile_id: int) -> Profile:
        profile = repo.get(profile_id)
        if profile is None or profile.user_id != user_id:  # IDOR-safe: same error for "not yours" and "missing"
            raise ProfileNotFoundError("Profile not found")
        return profile

    def _check_pin(self, profile: Profile, pin: str | None) -> None:
        key = f"profile:pin_attempts:{profile.id}"
        attempts = int(self._redis.get(key) or 0)
        if attempts >= self.MAX_PIN_ATTEMPTS:
            raise PinLockedError(int(self._redis.ttl(key) or self.PIN_LOCK_SECONDS))
        if not pin:
            raise PinRequiredError("This profile is PIN protected")
        if not check_password_hash(profile.pin_hash or "", pin):
            self._incr(keys=[key], args=[self.PIN_LOCK_SECONDS])
            raise PinInvalidError("Wrong PIN")
        self._redis.delete(key)

    def _max_profiles(self, user_id: int) -> int:
        entitlements: _EntitlementsLike | None = self._capabilities.optional("billing.entitlements")
        if entitlements is None:
            return DEFAULT_MAX_PROFILES
        return int(entitlements.for_user(user_id).max_profiles)


class ProfileDirectoryService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def get(self, profile_id: int) -> ProfileSummary | None:
        with self._uow() as uow:
            profile = ProfileRepository(uow.session).get(profile_id)
            return to_summary(profile) if profile else None

    def default_for(self, user_id: int) -> ProfileSummary:
        with self._uow() as uow:
            return to_summary(ProfileRepository(uow.session).ensure_default(user_id, self._clock.now()))

    def ids_for_user(self, user_id: int) -> list[int]:
        with self._uow() as uow:
            return [p.id for p in ProfileRepository(uow.session).for_user(user_id)]


class TokenProfileContextResolver:
    """Kernel ``ProfileContextResolver``.

    strict          — ``X-Profile-Token`` is mandatory.
    default_profile — missing header → the account's main profile (transition
                      mode so older clients keep working; prod forbids it).
    """

    HEADER = "X-Profile-Token"

    def __init__(self, tokens: TokenService, directory: ProfileDirectoryService, mode: str) -> None:
        self._tokens = tokens
        self._directory = directory
        self._mode = mode

    def resolve(self, req: Any, principal: Any) -> ProfileContext:
        raw = req.headers.get(self.HEADER)
        if raw:
            try:
                claims = self._tokens.verify(raw, expected=TokenType.PROFILE)
            except TokenInvalidError as exc:
                raise ApiError(f"PROFILE_{exc.code}", 401, "Profile token is invalid or expired") from exc
            if claims.sub != str(principal.id) or claims.ver != principal.token_version:
                raise ApiError("PROFILE_MISMATCH", 403, "Profile does not belong to this session")
            profile_id = int(claims.extra.get("profile_id", 0))
            profile = self._directory.get(profile_id)
            if profile is None or profile.user_id != principal.id:
                raise ApiError("PROFILE_NOT_FOUND", 401, "Profile no longer exists")
            return ProfileContext(profile.id, principal.id, profile.is_kids, profile.name)
        if self._mode == "default_profile":
            profile = self._directory.default_for(principal.id)
            return ProfileContext(profile.id, principal.id, profile.is_kids, profile.name)
        raise ApiError("MISSING_PROFILE_TOKEN", 400, "X-Profile-Token header is required")
