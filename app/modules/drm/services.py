"""DRM application services.

Security model (SEC-07, DATA-02):

* Content keys exist in clear only in process memory, for the duration of a
  key delivery / license issuance. At rest they are KeyVault envelopes.
* Every key/license request carries a *media grant* minted by playback for one
  (user, playback session). The service additionally checks that the session
  is live, belongs to the grant's user and plays *this* content — a grant for
  channel A can never unlock channel B.
* There is no separate DRM concurrency pool: a license exists only inside a
  playback session, whose slot is the single concurrency control.
* Every decision (issued, renewed, denied, delivered, exported, rotated) is
  audited in ``drm_events``.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.kernel.db import dialect_insert, pairs
from app.kernel.resilience.best_effort import best_effort
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.drm.api import (
    DrmStatsView,
    IssuedLicense,
    LicenseIssuer,
    LicenseRequest,
    LicenseRestrictions,
)
from app.modules.drm.domain import (
    AlreadyProtectedError,
    DrmConfigurationError,
    DrmError,
    DrmEventType,
    DrmSystem,
    DrmSystemNotEnabledError,
    DrmSystemUnavailableError,
    KeyNotFoundError,
    LicenseNotFoundError,
    LicenseStatus,
    PolicyInUseError,
    PolicyNameTakenError,
    PolicyNotFoundError,
    ProtectedContentNotFoundError,
    UnknownContentError,
    format_systems,
    lowest_resolution,
    parse_device_classes,
    parse_systems,
)
from app.modules.drm.models import DrmContent, DrmEvent, DrmLicense, DrmPolicy
from app.modules.drm.vault import KeyVault
from app.modules.playback.api import ContentCard, ContentDirectory, MediaGrant, SessionDirectory, SessionInactiveError
from app.shared_kernel.content import ContentRef

KEY_PATH_PREFIX = "/api/v1/drm/keys/"
LICENSE_PATH_PREFIX = "/api/v1/drm/licenses/"
EVENT_RETENTION_DAYS = 90


def key_path(key_id: str) -> str:
    return f"{KEY_PATH_PREFIX}{key_id}"


def license_path(system: str) -> str:
    return f"{LICENSE_PATH_PREFIX}{system}"


class _EntitlementsLike(Protocol):
    def for_user(self, user_id: int) -> Any: ...


class _CapabilitiesLike(Protocol):
    def optional(self, capability: str) -> Any | None: ...


# ── Views ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EffectivePolicy:
    """Policy values applied to a request (row or built-in default)."""

    id: int | None
    name: str
    max_resolution: str
    license_duration_s: int
    allow_offline: bool
    offline_validity_h: int
    allowed_device_classes: frozenset[str]
    require_hdcp: bool
    allow_screen_capture: bool

    @classmethod
    def of(cls, row: DrmPolicy) -> EffectivePolicy:
        return cls(
            id=row.id,
            name=row.name,
            max_resolution=row.max_resolution,
            license_duration_s=row.license_duration_s,
            allow_offline=bool(row.allow_offline),
            offline_validity_h=row.offline_validity_h,
            allowed_device_classes=parse_device_classes(row.allowed_device_classes),
            require_hdcp=bool(row.require_hdcp),
            allow_screen_capture=bool(row.allow_screen_capture),
        )


BUILTIN_DEFAULT_POLICY = EffectivePolicy(
    id=None,
    name="builtin-default",
    max_resolution="2160p",
    license_duration_s=600,
    allow_offline=False,
    offline_validity_h=48,
    allowed_device_classes=frozenset(),
    require_hdcp=False,
    allow_screen_capture=False,
)


@dataclass(frozen=True, slots=True)
class PolicyView:
    id: int
    name: str
    max_resolution: str
    license_duration_s: int
    allow_offline: bool
    offline_validity_h: int
    allowed_device_classes: list[str]
    require_hdcp: bool
    allow_screen_capture: bool
    is_default: bool
    created_at: datetime

    @classmethod
    def of(cls, row: DrmPolicy) -> PolicyView:
        return cls(
            id=row.id,
            name=row.name,
            max_resolution=row.max_resolution,
            license_duration_s=row.license_duration_s,
            allow_offline=bool(row.allow_offline),
            offline_validity_h=row.offline_validity_h,
            allowed_device_classes=sorted(parse_device_classes(row.allowed_device_classes)),
            require_hdcp=bool(row.require_hdcp),
            allow_screen_capture=bool(row.allow_screen_capture),
            is_default=bool(row.is_default),
            created_at=row.created_at,
        )


@dataclass(frozen=True, slots=True)
class ProtectedContentView:
    id: int
    content_ref: str
    title: str | None
    key_id: str
    systems: list[str]
    policy_id: int | None
    active_licenses: int
    key_rotated_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProtectionInfo:
    """What playback needs to know about a protected content (no key material)."""

    content_ref: str
    key_id: str
    systems: frozenset[DrmSystem]
    policy: EffectivePolicy


@dataclass(frozen=True, slots=True)
class KeyExport:
    """For the packager only (permission ``drm:keys``, audited)."""

    content_ref: str
    key_id: str
    key_hex: str
    key_uri: str
    systems: list[str]


@dataclass(frozen=True, slots=True)
class LicenseView:
    id: str
    user_id: int
    content_ref: str
    system: str
    status: str
    max_resolution: str | None
    renewals: int
    ip: str | None
    issued_at: datetime
    expires_at: datetime

    @classmethod
    def of(cls, row: DrmLicense) -> LicenseView:
        return cls(
            id=row.id,
            user_id=row.user_id,
            content_ref=row.content_ref,
            system=row.system,
            status=row.status,
            max_resolution=row.max_resolution,
            renewals=row.renewals,
            ip=row.ip,
            issued_at=row.issued_at,
            expires_at=row.expires_at,
        )


@dataclass(frozen=True, slots=True)
class DrmEventView:
    id: int
    event_type: str
    user_id: int | None
    content_ref: str | None
    license_id: str | None
    system: str | None
    error_code: str | None
    detail: str | None
    ip: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PolicyInput:
    name: str
    max_resolution: str = "2160p"
    license_duration_s: int = 600
    allow_offline: bool = False
    offline_validity_h: int = 48
    allowed_device_classes: list[str] = field(default_factory=list)
    require_hdcp: bool = False
    allow_screen_capture: bool = False
    is_default: bool = False


# ── Audit ──────────────────────────────────────────────────────────────────


def audit(
    session: Session,
    event_type: DrmEventType,
    at: datetime,
    *,
    user_id: int | None = None,
    content_ref: str | None = None,
    license_id: str | None = None,
    system: str | None = None,
    error_code: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    session.add(
        DrmEvent(
            event_type=str(event_type),
            user_id=user_id,
            content_ref=content_ref,
            license_id=license_id,
            system=system,
            error_code=error_code[:50] if error_code else None,
            detail=detail[:255] if detail else None,
            ip=ip[:45] if ip else None,
            created_at=at,
        )
    )


def _resolve_policy(session: Session, content: DrmContent) -> EffectivePolicy:
    if content.policy_id is not None:
        row = session.get(DrmPolicy, content.policy_id)
        if row is not None:
            return EffectivePolicy.of(row)
    default = session.execute(select(DrmPolicy).where(DrmPolicy.is_default.is_(True))).scalar_one_or_none()
    return EffectivePolicy.of(default) if default is not None else BUILTIN_DEFAULT_POLICY


def _revoke_active(session: Session, content_ref: str, now: datetime) -> int:
    return int(
        session.execute(
            update(DrmLicense)
            .where(DrmLicense.content_ref == content_ref, DrmLicense.status == str(LicenseStatus.ACTIVE))
            .values(status=str(LicenseStatus.REVOKED), ended_at=now)
        ).rowcount
        or 0
    )


# ── Policies ───────────────────────────────────────────────────────────────


class PolicyService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def all(self) -> list[PolicyView]:
        with self._uow() as uow:
            rows = uow.session.execute(select(DrmPolicy).order_by(DrmPolicy.name)).scalars()
            return [PolicyView.of(r) for r in rows]

    def create(self, data: PolicyInput) -> PolicyView:
        with self._uow() as uow:
            if uow.session.execute(select(DrmPolicy.id).where(DrmPolicy.name == data.name)).first():
                raise PolicyNameTakenError(f"policy '{data.name}' already exists")
            if data.is_default:
                self._clear_default(uow.session)
            row = DrmPolicy(
                name=data.name,
                max_resolution=data.max_resolution,
                license_duration_s=data.license_duration_s,
                allow_offline=data.allow_offline,
                offline_validity_h=data.offline_validity_h,
                allowed_device_classes=",".join(sorted(parse_device_classes(",".join(data.allowed_device_classes))))
                or None,
                require_hdcp=data.require_hdcp,
                allow_screen_capture=data.allow_screen_capture,
                is_default=data.is_default,
                created_at=self._clock.now(),
                updated_at=self._clock.now(),
            )
            uow.session.add(row)
            uow.flush()
            return PolicyView.of(row)

    def update(self, policy_id: int, changes: dict[str, Any]) -> PolicyView:
        with self._uow() as uow:
            row = self._get(uow.session, policy_id)
            if "name" in changes and changes["name"] != row.name:
                taken = uow.session.execute(
                    select(DrmPolicy.id).where(DrmPolicy.name == changes["name"], DrmPolicy.id != policy_id)
                ).first()
                if taken:
                    raise PolicyNameTakenError(f"policy '{changes['name']}' already exists")
            if changes.get("is_default"):
                self._clear_default(uow.session, keep=policy_id)
            for name, raw in changes.items():
                value = (
                    ",".join(sorted(parse_device_classes(",".join(raw or [])))) or None
                    if name == "allowed_device_classes"
                    else raw
                )
                setattr(row, name, value)
            row.updated_at = self._clock.now()
            uow.flush()
            return PolicyView.of(row)

    def delete(self, policy_id: int) -> None:
        with self._uow() as uow:
            row = self._get(uow.session, policy_id)
            in_use = uow.session.execute(
                select(func.count(DrmContent.id)).where(DrmContent.policy_id == policy_id)
            ).scalar_one()
            if in_use:
                raise PolicyInUseError(f"policy is assigned to {in_use} protected content item(s)")
            uow.session.delete(row)

    @staticmethod
    def _get(session: Session, policy_id: int) -> DrmPolicy:
        row = session.get(DrmPolicy, policy_id)
        if row is None:
            raise PolicyNotFoundError("DRM policy not found")
        return row

    @staticmethod
    def _clear_default(session: Session, keep: int | None = None) -> None:
        stmt = update(DrmPolicy).where(DrmPolicy.is_default.is_(True)).values(is_default=False)
        if keep is not None:
            stmt = stmt.where(DrmPolicy.id != keep)
        session.execute(stmt)
        session.flush()


# ── Content protection (key custody) ──────────────────────────────────────


class ProtectionService:
    def __init__(self, uow: UnitOfWorkFactory, vault: KeyVault, clock: Clock, content: ContentDirectory) -> None:
        self._uow = uow
        self._vault = vault
        self._clock = clock
        self._content = content

    # playback path (read-only, no key material) ---------------------------
    def lookup(self, content_ref: str) -> ProtectionInfo | None:
        with self._uow() as uow:
            row = uow.session.execute(
                select(DrmContent).where(DrmContent.content_ref == content_ref)
            ).scalar_one_or_none()
            if row is None:
                return None
            return ProtectionInfo(
                row.content_ref, row.key_id, parse_systems(row.systems), _resolve_policy(uow.session, row)
            )

    # admin ----------------------------------------------------------------
    def page(self, *, page: int, per_page: int) -> tuple[list[ProtectedContentView], int]:
        with self._uow() as uow:
            total = int(uow.session.execute(select(func.count(DrmContent.id))).scalar_one())
            rows = list(
                uow.session.execute(
                    select(DrmContent).order_by(DrmContent.id.desc()).offset((page - 1) * per_page).limit(per_page)
                ).scalars()
            )
            return self._views(uow.session, rows), total

    def get(self, content_id: int) -> ProtectedContentView:
        with self._uow() as uow:
            return self._views(uow.session, [self._get(uow.session, content_id)])[0]

    def protect(
        self, *, content_ref: str, systems: list[str], policy_id: int | None, actor_id: int
    ) -> ProtectedContentView:
        ref = ContentRef.parse(content_ref)
        if self._content.describe(ref) is None:
            raise UnknownContentError(f"content '{ref}' does not exist")
        parsed = parse_systems(systems)
        now = self._clock.now()
        with self._uow() as uow:
            if uow.session.execute(select(DrmContent.id).where(DrmContent.content_ref == str(ref))).first():
                raise AlreadyProtectedError(f"content '{ref}' is already protected")
            if policy_id is not None and uow.session.get(DrmPolicy, policy_id) is None:
                raise PolicyNotFoundError("DRM policy not found")
            row = DrmContent(
                content_ref=str(ref),
                key_id=secrets.token_hex(16),
                wrapped_key=self._vault.wrap(secrets.token_bytes(16)),
                systems=format_systems(parsed),
                policy_id=policy_id,
                created_at=now,
                updated_at=now,
            )
            uow.session.add(row)
            uow.flush()
            audit(
                uow.session,
                DrmEventType.CONTENT_PROTECTED,
                now,
                user_id=actor_id,
                content_ref=row.content_ref,
                detail=f"systems={row.systems}",
            )
            return self._views(uow.session, [row])[0]

    def update(
        self, content_id: int, *, systems: list[str] | None, policy_id: int | None, clear_policy: bool
    ) -> ProtectedContentView:
        with self._uow() as uow:
            row = self._get(uow.session, content_id)
            if systems is not None:
                row.systems = format_systems(parse_systems(systems))
            if clear_policy:
                row.policy_id = None
            elif policy_id is not None:
                if uow.session.get(DrmPolicy, policy_id) is None:
                    raise PolicyNotFoundError("DRM policy not found")
                row.policy_id = policy_id
            row.updated_at = self._clock.now()
            uow.flush()
            return self._views(uow.session, [row])[0]

    def rotate_key(self, content_id: int, *, actor_id: int) -> ProtectedContentView:
        """New KID + key; every active license for the content is revoked. The
        content must be re-packaged with the new key (export it after rotating)."""
        now = self._clock.now()
        with self._uow() as uow:
            row = self._get(uow.session, content_id)
            old_kid = row.key_id
            row.key_id = secrets.token_hex(16)
            row.wrapped_key = self._vault.wrap(secrets.token_bytes(16))
            row.key_rotated_at = now
            row.updated_at = now
            revoked = _revoke_active(uow.session, row.content_ref, now)
            audit(
                uow.session,
                DrmEventType.KEY_ROTATED,
                now,
                user_id=actor_id,
                content_ref=row.content_ref,
                detail=f"old_kid={old_kid} revoked_licenses={revoked}",
            )
            uow.flush()
            return self._views(uow.session, [row])[0]

    def unprotect(self, content_id: int, *, actor_id: int) -> None:
        """Crypto-shredding: the wrapped key is destroyed with the row."""
        now = self._clock.now()
        with self._uow() as uow:
            row = self._get(uow.session, content_id)
            revoked = _revoke_active(uow.session, row.content_ref, now)
            audit(
                uow.session,
                DrmEventType.CONTENT_UNPROTECTED,
                now,
                user_id=actor_id,
                content_ref=row.content_ref,
                detail=f"revoked_licenses={revoked}",
            )
            uow.session.delete(row)

    def export_key(self, content_id: int, *, actor_id: int, ip: str) -> KeyExport:
        now = self._clock.now()
        with self._uow() as uow:
            row = self._get(uow.session, content_id)
            key = self._vault.unwrap(row.wrapped_key)
            audit(uow.session, DrmEventType.KEY_EXPORTED, now, user_id=actor_id, content_ref=row.content_ref, ip=ip)
            return KeyExport(
                content_ref=row.content_ref,
                key_id=row.key_id,
                key_hex=key.hex(),
                key_uri=key_path(row.key_id),
                systems=sorted(str(s) for s in parse_systems(row.systems)),
            )

    def rewrap_all(self, batch: int = 500) -> int:
        """KEK rotation: re-wrap every content key with the newest KEK."""
        done = 0
        last_id = 0
        while True:
            with self._uow() as uow:
                rows = list(
                    uow.session.execute(
                        select(DrmContent).where(DrmContent.id > last_id).order_by(DrmContent.id).limit(batch)
                    ).scalars()
                )
                for row in rows:
                    row.wrapped_key = self._vault.rewrap(row.wrapped_key)
                    last_id = row.id
            done += len(rows)
            if len(rows) < batch:
                return done

    # event consumer (inside the consumer's UoW) ---------------------------
    def remove_for_content(self, session: Session, content_ref: str) -> bool:
        now = self._clock.now()
        row = session.execute(select(DrmContent).where(DrmContent.content_ref == content_ref)).scalar_one_or_none()
        if row is None:
            return False
        revoked = _revoke_active(session, content_ref, now)
        audit(
            session,
            DrmEventType.CONTENT_UNPROTECTED,
            now,
            content_ref=content_ref,
            detail=f"reason=content_removed revoked_licenses={revoked}",
        )
        session.delete(row)
        return True

    # helpers --------------------------------------------------------------
    @staticmethod
    def _get(session: Session, content_id: int) -> DrmContent:
        row = session.get(DrmContent, content_id)
        if row is None:
            raise ProtectedContentNotFoundError("protected content not found")
        return row

    def _views(self, session: Session, rows: list[DrmContent]) -> list[ProtectedContentView]:
        if not rows:
            return []
        refs = [r.content_ref for r in rows]
        counts = pairs(
            session.execute(
                select(DrmLicense.content_ref, func.count(DrmLicense.id))
                .where(DrmLicense.content_ref.in_(refs), DrmLicense.status == str(LicenseStatus.ACTIVE))
                .group_by(DrmLicense.content_ref)
            ).all()
        )
        cards: dict[str, ContentCard] = best_effort(lambda: self._content.cards(refs), op="drm.content_cards") or {}
        return [
            ProtectedContentView(
                id=r.id,
                content_ref=r.content_ref,
                title=cards[r.content_ref].title if r.content_ref in cards else None,
                key_id=r.key_id,
                systems=sorted(str(s) for s in parse_systems(r.systems)),
                policy_id=r.policy_id,
                active_licenses=int(counts.get(r.content_ref, 0)),
                key_rotated_at=r.key_rotated_at,
                created_at=r.created_at,
            )
            for r in rows
        ]


# ── Issuer registry (built lazily from the extension point) ───────────────


class IssuerRegistry:
    def __init__(self, factory: Callable[[], list[LicenseIssuer]]) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._issuers: dict[str, LicenseIssuer] | None = None

    def _all(self) -> dict[str, LicenseIssuer]:
        if self._issuers is None:
            with self._lock:
                if self._issuers is None:
                    issuers: dict[str, LicenseIssuer] = {}
                    for issuer in self._factory():
                        system = str(DrmSystem(issuer.system))
                        if system == DrmSystem.AES_128:
                            raise DrmConfigurationError("aes-128 is served by key delivery, not by a license issuer")
                        if system in issuers:
                            raise DrmConfigurationError(f"two license issuers for DRM system '{system}'")
                        issuers[system] = issuer
                    self._issuers = issuers
        return self._issuers

    def available(self) -> frozenset[str]:
        return frozenset(self._all())

    def get(self, system: str) -> LicenseIssuer:
        issuer = self._all().get(system)
        if issuer is None:
            raise DrmSystemUnavailableError(f"no license issuer installed for DRM system '{system}'")
        return issuer


# ── Licenses & key delivery (player path) ─────────────────────────────────


class LicenseService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        vault: KeyVault,
        clock: Clock,
        sessions: SessionDirectory,
        issuers: IssuerRegistry,
        capabilities: _CapabilitiesLike,
    ) -> None:
        self._uow = uow
        self._vault = vault
        self._clock = clock
        self._sessions = sessions
        self._issuers = issuers
        self._capabilities = capabilities

    def deliver_key(self, *, grant: MediaGrant, key_id: str, ip: str) -> bytes:
        """HLS AES-128 key delivery."""
        with self._denials_audited(grant, str(DrmSystem.AES_128), ip):
            now = self._clock.now()
            with self._uow() as uow:
                content, session_ref = self._authorize(uow.session, grant, DrmSystem.AES_128)
                if content.key_id != key_id:
                    raise KeyNotFoundError("key does not belong to the session's content")
                policy = _resolve_policy(uow.session, content)
                license_id = self._upsert_license(
                    uow.session,
                    grant,
                    content,
                    DrmSystem.AES_128,
                    self.restrictions(grant.user_id, policy),
                    self._expiry(policy, grant, now),
                    ip,
                    now,
                )
                audit(
                    uow.session,
                    DrmEventType.KEY_DELIVERED,
                    now,
                    user_id=grant.user_id,
                    content_ref=session_ref,
                    license_id=license_id,
                    system=str(DrmSystem.AES_128),
                    ip=ip,
                )
                return self._vault.unwrap(content.wrapped_key)

    def issue_license(self, *, grant: MediaGrant, system: str, challenge: bytes, ip: str) -> IssuedLicense:
        """EME license (ClearKey / vendor systems). Repeated calls renew."""
        with self._denials_audited(grant, system, ip):
            try:
                drm_system = DrmSystem(system)
            except ValueError:
                raise DrmSystemNotEnabledError(f"unknown DRM system '{system}'") from None
            if not drm_system.uses_license_server:
                raise DrmSystemNotEnabledError("aes-128 uses key delivery, not a license server")
            issuer = self._issuers.get(str(drm_system))
            now = self._clock.now()
            with self._uow() as uow:
                content, _ = self._authorize(uow.session, grant, drm_system)
                policy = _resolve_policy(uow.session, content)
                restrictions = self.restrictions(grant.user_id, policy)
                expires_at = self._expiry(policy, grant, now)
                issued = issuer.issue(
                    LicenseRequest(
                        system=str(drm_system),
                        challenge=challenge,
                        key_id=content.key_id,
                        content_key=self._vault.unwrap(content.wrapped_key),
                        restrictions=restrictions,
                        expires_at=expires_at,
                        user_id=grant.user_id,
                        session_token=grant.session_token,
                    )
                )
                self._upsert_license(uow.session, grant, content, drm_system, restrictions, expires_at, ip, now)
                return issued

    # consumers / jobs -------------------------------------------------------
    def release_session(self, session: Session, session_token: str) -> int:
        now = self._clock.now()
        rows = list(
            session.execute(
                select(DrmLicense).where(
                    DrmLicense.session_token == session_token, DrmLicense.status == str(LicenseStatus.ACTIVE)
                )
            ).scalars()
        )
        for row in rows:
            row.status = str(LicenseStatus.RELEASED)
            row.ended_at = now
            audit(
                session,
                DrmEventType.LICENSE_RELEASED,
                now,
                user_id=row.user_id,
                content_ref=row.content_ref,
                license_id=row.id,
                system=row.system,
            )
        return len(rows)

    def revoke(self, license_id: str, *, actor_id: int) -> LicenseView:
        now = self._clock.now()
        with self._uow() as uow:
            row = uow.session.get(DrmLicense, license_id)
            if row is None:
                raise LicenseNotFoundError("license not found")
            if row.status == str(LicenseStatus.ACTIVE):
                row.status = str(LicenseStatus.REVOKED)
                row.ended_at = now
                audit(
                    uow.session,
                    DrmEventType.LICENSE_REVOKED,
                    now,
                    user_id=row.user_id,
                    content_ref=row.content_ref,
                    license_id=row.id,
                    system=row.system,
                    detail=f"by_admin={actor_id}",
                )
            return LicenseView.of(row)

    def expire_due(self) -> int:
        now = self._clock.now()
        with self._uow() as uow:
            return int(
                uow.session.execute(
                    update(DrmLicense)
                    .where(DrmLicense.status == str(LicenseStatus.ACTIVE), DrmLicense.expires_at <= now)
                    .values(status=str(LicenseStatus.EXPIRED), ended_at=now)
                ).rowcount
                or 0
            )

    def purge_events(self, retention_days: int = EVENT_RETENTION_DAYS) -> int:
        cutoff = self._clock.now() - timedelta(days=retention_days)
        with self._uow() as uow:
            return int(uow.session.execute(delete(DrmEvent).where(DrmEvent.created_at < cutoff)).rowcount or 0)

    # internals --------------------------------------------------------------
    def _authorize(self, session: Session, grant: MediaGrant, system: DrmSystem) -> tuple[DrmContent, str]:
        view = self._sessions.describe(grant.session_token)
        if view is None or view.user_id != grant.user_id:
            raise SessionInactiveError("playback session ended")
        content = session.execute(
            select(DrmContent).where(DrmContent.content_ref == view.content_ref)
        ).scalar_one_or_none()
        if content is None:
            raise KeyNotFoundError("the session's content is not DRM protected")
        if system not in parse_systems(content.systems):
            raise DrmSystemNotEnabledError(f"'{system}' is not enabled for this content")
        return content, view.content_ref

    def restrictions(self, user_id: int, policy: EffectivePolicy) -> LicenseRestrictions:
        entitlements: _EntitlementsLike | None = self._capabilities.optional("billing.entitlements")
        account_resolution: str | None = None
        account_offline = True
        if entitlements is not None:
            granted = entitlements.for_user(user_id)
            account_resolution = granted.max_resolution
            account_offline = bool(granted.offline_downloads)
        return LicenseRestrictions(
            max_resolution=lowest_resolution(policy.max_resolution, account_resolution),
            require_hdcp=policy.require_hdcp,
            allow_screen_capture=policy.allow_screen_capture,
            allow_offline=policy.allow_offline and account_offline,
            offline_validity_h=policy.offline_validity_h,
        )

    @staticmethod
    def _expiry(policy: EffectivePolicy, grant: MediaGrant, now: datetime) -> datetime:
        by_policy = now + timedelta(seconds=policy.license_duration_s)
        by_grant = datetime.fromtimestamp(grant.expires_at, tz=UTC)
        return min(by_policy, by_grant)

    def _upsert_license(
        self,
        session: Session,
        grant: MediaGrant,
        content: DrmContent,
        system: DrmSystem,
        restrictions: LicenseRestrictions,
        expires_at: datetime,
        ip: str,
        now: datetime,
    ) -> str:
        """Race-free issue-or-renew on (session_token, system)."""
        table = DrmLicense.__table__
        stmt = dialect_insert(session, table).values(
            id=secrets.token_hex(16),
            user_id=grant.user_id,
            session_token=grant.session_token,
            content_ref=content.content_ref,
            key_id=content.key_id,
            system=str(system),
            status=str(LicenseStatus.ACTIVE),
            max_resolution=restrictions.max_resolution,
            renewals=0,
            ip=ip[:45],
            issued_at=now,
            expires_at=expires_at,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["session_token", "system"],
                set_={
                    "status": str(LicenseStatus.ACTIVE),
                    "key_id": content.key_id,
                    "max_resolution": restrictions.max_resolution,
                    "renewals": table.c.renewals + 1,
                    "ip": ip[:45],
                    "expires_at": expires_at,
                    "ended_at": None,
                },
            )
        )
        row = session.execute(
            select(DrmLicense.id, DrmLicense.renewals).where(
                DrmLicense.session_token == grant.session_token, DrmLicense.system == str(system)
            )
        ).one()
        audit(
            session,
            DrmEventType.LICENSE_ISSUED if row.renewals == 0 else DrmEventType.LICENSE_RENEWED,
            now,
            user_id=grant.user_id,
            content_ref=content.content_ref,
            license_id=row.id,
            system=str(system),
            ip=ip,
        )
        return str(row.id)

    @contextmanager
    def _denials_audited(self, grant: MediaGrant, system: str, ip: str) -> Iterator[None]:
        try:
            yield
        except (DrmError, SessionInactiveError) as exc:
            code = getattr(exc, "error_code", None) or type(exc).__name__
            message = str(exc)

            def record() -> None:
                with self._uow() as uow:
                    audit(
                        uow.session,
                        DrmEventType.LICENSE_DENIED,
                        self._clock.now(),
                        user_id=grant.user_id,
                        system=system[:20],
                        error_code=code,
                        detail=message,
                        ip=ip,
                    )

            best_effort(record, op="drm.audit_denial")
            raise


# ── Monitoring (capability drm.stats + admin views) ───────────────────────


class DrmMonitoringService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def stats(self) -> DrmStatsView:
        now = self._clock.now()
        since = now - timedelta(hours=24)
        with self._uow() as uow:
            s = uow.session
            by_type = pairs(
                s.execute(
                    select(DrmEvent.event_type, func.count(DrmEvent.id))
                    .where(DrmEvent.created_at >= since)
                    .group_by(DrmEvent.event_type)
                ).all()
            )
            return DrmStatsView(
                protected_contents=int(s.execute(select(func.count(DrmContent.id))).scalar_one()),
                active_licenses=int(
                    s.execute(
                        select(func.count(DrmLicense.id)).where(
                            DrmLicense.status == str(LicenseStatus.ACTIVE), DrmLicense.expires_at > now
                        )
                    ).scalar_one()
                ),
                issued_24h=int(by_type.get(str(DrmEventType.LICENSE_ISSUED), 0)),
                denied_24h=int(by_type.get(str(DrmEventType.LICENSE_DENIED), 0)),
                keys_delivered_24h=int(by_type.get(str(DrmEventType.KEY_DELIVERED), 0)),
            )

    def active_licenses(self, limit: int) -> list[LicenseView]:
        now = self._clock.now()
        with self._uow() as uow:
            rows = uow.session.execute(
                select(DrmLicense)
                .where(DrmLicense.status == str(LicenseStatus.ACTIVE), DrmLicense.expires_at > now)
                .order_by(DrmLicense.issued_at.desc())
                .limit(limit)
            ).scalars()
            return [LicenseView.of(r) for r in rows]

    def events(self, *, limit: int, event_type: str | None, before_id: int | None) -> list[DrmEventView]:
        with self._uow() as uow:
            stmt = select(DrmEvent).order_by(DrmEvent.id.desc()).limit(limit)
            if event_type:
                stmt = stmt.where(DrmEvent.event_type == str(DrmEventType(event_type)))
            if before_id:
                stmt = stmt.where(DrmEvent.id < before_id)
            return [
                DrmEventView(
                    id=e.id,
                    event_type=e.event_type,
                    user_id=e.user_id,
                    content_ref=e.content_ref,
                    license_id=e.license_id,
                    system=e.system,
                    error_code=e.error_code,
                    detail=e.detail,
                    ip=e.ip,
                    created_at=e.created_at,
                )
                for e in uow.session.execute(stmt).scalars()
            ]
