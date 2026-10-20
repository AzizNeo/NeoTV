"""Playback session lifecycle."""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import select

from app.kernel.capabilities import CapabilityIndex
from app.kernel.http.profile_context import ProfileContext
from app.kernel.observability.metrics import Metrics
from app.kernel.security.device_keys import DeviceKeys
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWork, UnitOfWorkFactory
from app.modules.playback.api import (
    ActiveSessionView,
    ContentDescriptor,
    KeepAlive,
    OpenedStream,
    PlaybackContext,
    PlaybackRefusedError,
    ResolvedSource,
)
from app.modules.playback.concurrency import StreamConcurrencyGuard
from app.modules.playback.gate import ContentNotFoundError, NoContentProviderError, PlaybackDeniedError, PlaybackGate
from app.modules.playback.grants import MEDIA_SESSION_MARK
from app.modules.playback.models import PlaybackEventRecord, PlaybackSessionRecord, QoeRecord
from app.shared_kernel.content import ContentRef, InvalidContentRefError
from app.shared_kernel.events import PlaybackSessionEnded, PlaybackSessionStarted

_log = logging.getLogger("playback")

HEARTBEAT_INTERVAL_S = 10
#: Device labels the player sends (useQoe.deviceType); anything else is "other" (bounded cardinality).
_QOE_DEVICES = frozenset({"tv", "tablet", "mobile", "desktop"})
EVENT_TYPES = frozenset({"play", "pause", "resume", "seek", "stop", "complete", "error"})


class StreamLimitExceededError(Exception):
    def __init__(self, active: int, limit: int) -> None:
        super().__init__("Maximum number of simultaneous streams reached")
        self.details = {"active_sessions": active, "max_allowed": limit}


class SessionExpiredError(Exception):
    pass


class _EntitlementsLike(Protocol):
    def for_user(self, user_id: int) -> Any: ...


@dataclass(frozen=True, slots=True)
class OpenedSession:
    token: str
    source: ResolvedSource
    descriptor: ContentDescriptor
    heartbeat_interval_s: int
    expires_at: int


class PlaybackSessionService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        gate_provider: Any,
        guard: StreamConcurrencyGuard,
        device_keys: DeviceKeys,
        capabilities: CapabilityIndex,
        settings: Settings,
        clock: Clock,
        metrics: Metrics,
    ) -> None:
        self._uow = uow
        self._gate_provider = gate_provider
        self._guard = guard
        self._device_keys = device_keys
        self._capabilities = capabilities
        self._settings = settings
        self._clock = clock
        self._metrics = metrics

    def _gate(self) -> PlaybackGate:
        return self._gate_provider()

    # ── open ───────────────────────────────────────────────────────────────
    def open(
        self,
        *,
        user_id: int,
        profile: ProfileContext,
        content_ref: str,
        client_device_id: str | None,
        ip: str,
        user_agent: str,
        keepalive: KeepAlive = "heartbeat",
    ) -> OpenedSession:
        ref = ContentRef.parse(content_ref)
        device_key = self._device_keys.key(user_id, client_device_id, user_agent)
        token = (MEDIA_SESSION_MARK if keepalive == "media" else "") + secrets.token_urlsafe(24)
        expires_at = int(time.time()) + self._settings.playback_grant_ttl_s
        ctx = PlaybackContext(
            user_id=user_id,
            profile_id=profile.profile_id,
            is_kids=profile.is_kids,
            device_key=device_key,
            ip=ip,
            user_agent=user_agent[:255],
            content=ref,
            session_token=token,
            grant_expires_at=expires_at,
        )
        gate = self._gate()
        try:
            descriptor = gate.authorize(ctx)  # side-effect free rules first
        except Exception:
            self._metrics.playback_open.labels("denied").inc()
            raise

        # Switching channels on the same device replaces the previous stream — atomically, inside acquire
        # (a check-then-release here raced when one device opened twice at once).
        limit = self._max_streams(user_id)
        acquired = self._guard.acquire(user_id=user_id, token=token, limit=limit, device_key=device_key)
        if not acquired.granted:
            self._metrics.playback_open.labels("limit").inc()
            raise StreamLimitExceededError(acquired.active, limit)
        if acquired.replaced:
            with self._uow() as uow:
                for previous in acquired.replaced:
                    self._end_record(uow, previous, "replaced")
        try:
            source = gate.resolve(ctx, descriptor)
            now = self._clock.now()
            with self._uow() as uow:
                uow.session.add(
                    PlaybackSessionRecord(
                        token=token,
                        user_id=user_id,
                        profile_id=profile.profile_id,
                        content_ref=str(ref),
                        device_key=device_key,
                        ip=ip[:45],
                        user_agent=user_agent[:255],
                        started_at=now,
                        last_heartbeat_at=now,
                    )
                )
                uow.outbox.add(
                    PlaybackSessionStarted(
                        session_token=token,
                        user_id=user_id,
                        profile_id=profile.profile_id,
                        content_ref=str(ref),
                        started_at=now.isoformat(),
                    )
                )
        except Exception:
            self._guard.release(token)
            self._metrics.playback_open.labels("error").inc()
            raise
        self._metrics.playback_open.labels("ok").inc()
        return OpenedSession(token, source, descriptor, HEARTBEAT_INTERVAL_S, expires_at)

    # ── heartbeat / release ────────────────────────────────────────────────
    def heartbeat(self, *, user_id: int, token: str) -> None:
        if not self._guard.heartbeat(user_id=user_id, token=token):
            raise SessionExpiredError("Playback session expired")
        self.touch_record(user_id, token)

    def touch_record(self, user_id: int, token: str) -> None:
        """Liveness into the audit record (watched time is computed from it when the session ends)."""
        with self._uow() as uow:
            record = uow.session.get(PlaybackSessionRecord, token)
            if record is not None and record.user_id == user_id:
                record.last_heartbeat_at = self._clock.now()

    def release(self, token: str, *, reason: str = "client") -> bool:
        owner = self._guard.release(token)
        with self._uow() as uow:
            ended = self._end_record(uow, token, reason)
        return owner is not None or ended

    def release_user(self, user_id: int, *, reason: str) -> int:
        tokens = self._guard.tokens(user_id)
        for token in tokens:
            self.release(token, reason=reason)
        return len(tokens)

    def release_device(self, user_id: int, device_key: str, *, reason: str) -> int:
        released = 0
        for token in self._guard.tokens(user_id):
            owner = self._guard.owner(token)
            if owner is not None and owner.device_key == device_key:
                self.release(token, reason=reason)
                released += 1
        return released

    def enforce_limit(self, user_id: int, max_streams: int, *, reason: str) -> int:
        """After a downgrade, end the *least recently active* streams above the new limit."""
        tokens = self._guard.tokens(user_id)  # ascending by last heartbeat
        excess = tokens[: max(0, len(tokens) - max(0, max_streams))]
        for token in excess:
            self.release(token, reason=reason)
        return len(excess)

    def expire_stale(self) -> int:
        """Close audit records whose Redis slot is gone (client vanished without release)."""
        cutoff = self._clock.now() - timedelta(seconds=self._guard.window * 2)
        closed = 0
        with self._uow() as uow:
            stale = (
                uow.session.execute(
                    select(PlaybackSessionRecord.token)
                    .where(PlaybackSessionRecord.ended_at.is_(None), PlaybackSessionRecord.last_heartbeat_at < cutoff)
                    .limit(1000)
                )
                .scalars()
                .all()
            )
            for token in stale:
                if not self._guard.is_active(token) and self._end_record(uow, token, "timeout"):
                    closed += 1
        return closed

    def _end_record(self, uow: UnitOfWork, token: str, reason: str) -> bool:
        record = uow.session.get(PlaybackSessionRecord, token)
        if record is None or record.ended_at is not None:
            return False
        now = self._clock.now()
        record.ended_at = now
        record.end_reason = reason[:20]
        last_alive = max(record.last_heartbeat_at, record.started_at)
        watched = int(
            max(
                0.0,
                (min(now, last_alive + timedelta(seconds=HEARTBEAT_INTERVAL_S)) - record.started_at).total_seconds(),
            )
        )
        uow.outbox.add(
            PlaybackSessionEnded(
                session_token=token,
                user_id=record.user_id,
                profile_id=record.profile_id,
                content_ref=record.content_ref,
                ended_at=now.isoformat(),
                watched_seconds=watched,
            )
        )
        return True

    # ── telemetry ─────────────────────────────────────────────────────────
    def record_event(
        self,
        *,
        user_id: int,
        profile_id: int,
        content_ref: str,
        event_type: str,
        position_s: int,
        session_token: str | None,
    ) -> None:
        ref = ContentRef.parse(content_ref)
        with self._uow() as uow:
            uow.session.add(
                PlaybackEventRecord(
                    user_id=user_id,
                    profile_id=profile_id,
                    content_ref=str(ref),
                    event_type=event_type,
                    position_s=max(0, position_s),
                    session_token=session_token,
                    created_at=self._clock.now(),
                )
            )

    def record_qoe(self, *, user_id: int, data: dict[str, Any]) -> int:
        """Stores every report (unchanged contract); feeds the experience metrics only from a trusted
        one: the session is this user's and this is its first report. The client sends one report
        per session on close, so a second one is a bug or an attempt to skew the dashboards."""
        ref = ContentRef.parse(data.pop("content_ref"))
        token = data.get("session_token")
        with self._uow() as uow:
            lifetime_s: float | None = None
            if token:
                session = uow.session.get(PlaybackSessionRecord, token)
                first = uow.session.execute(
                    select(QoeRecord.id).where(QoeRecord.session_token == token).limit(1)
                ).first()
                if session is not None and session.user_id == user_id and first is None:
                    lifetime_s = (self._clock.now() - session.started_at).total_seconds()
            record = QoeRecord(user_id=user_id, content_ref=str(ref), created_at=self._clock.now(), **data)
            uow.session.add(record)
            uow.session.flush([record])
            record_id = int(record.id)
        if lifetime_s is not None:  # after the commit: a rolled-back report is never counted
            self._observe_qoe(data, lifetime_s)
        return record_id

    def _observe_qoe(self, data: dict[str, Any], lifetime_s: float) -> None:
        device = data.get("device_type") if data.get("device_type") in _QOE_DEVICES else "other"
        # A session cannot have played or stalled longer than it existed (+ a little clock slack).
        ceiling = max(0.0, lifetime_s) + 5
        if data.get("startup_time_ms") is not None:
            self._metrics.playback_startup.labels(device).observe(min(data["startup_time_ms"] / 1000, ceiling))
        self._metrics.playback_watch.labels(device).inc(min(float(data.get("watch_duration_s") or 0), ceiling))
        self._metrics.playback_rebuffer.labels(device).inc(min((data.get("rebuffer_duration_ms") or 0) / 1000, ceiling))
        self._metrics.playback_rebuffer_events.labels(device).inc(int(data.get("rebuffer_count") or 0))

    def active_count(self) -> int:
        return self._guard.total_active()

    def active_for_user(self, user_id: int) -> int:
        return self._guard.active_count(user_id)

    def _max_streams(self, user_id: int) -> int:
        entitlements: _EntitlementsLike | None = self._capabilities.optional("billing.entitlements")
        if entitlements is None:
            return self._settings.default_max_streams
        return int(entitlements.for_user(user_id).max_streams)


class SessionOpenerService:
    """Capability ``playback.open`` — the web player's use case, with refusals as one named error."""

    def __init__(self, sessions: PlaybackSessionService) -> None:
        self._sessions = sessions

    def open(
        self,
        *,
        user_id: int,
        profile_id: int,
        is_kids: bool,
        content_ref: str,
        client_device_id: str,
        ip: str,
        user_agent: str,
        keepalive: KeepAlive = "heartbeat",
    ) -> OpenedStream:
        try:
            opened = self._sessions.open(
                user_id=user_id,
                profile=ProfileContext(profile_id=profile_id, user_id=user_id, is_kids=is_kids),
                content_ref=content_ref,
                client_device_id=client_device_id,
                ip=ip,
                user_agent=user_agent,
                keepalive=keepalive,
            )
        except StreamLimitExceededError as exc:
            raise PlaybackRefusedError("STREAM_LIMIT_EXCEEDED", str(exc)) from exc
        except PlaybackDeniedError as exc:
            raise PlaybackRefusedError(exc.code, str(exc)) from exc
        except (ContentNotFoundError, NoContentProviderError, InvalidContentRefError) as exc:
            raise PlaybackRefusedError("CONTENT_NOT_FOUND", "Content not found") from exc
        return OpenedStream(
            session_token=opened.token,
            manifest_url=opened.source.manifest_url,
            mime_type=opened.source.mime_type,
            is_live=opened.source.is_live,
            drm=opened.source.drm,
        )

    def release(self, session_token: str) -> bool:
        return self._sessions.release(session_token, reason="client")

    def active_for_user(self, user_id: int) -> int:
        return self._sessions.active_for_user(user_id)


class SessionDirectoryService:
    """Capability ``playback.sessions``."""

    def __init__(self, guard: StreamConcurrencyGuard, sessions: PlaybackSessionService, uow: UnitOfWorkFactory) -> None:
        self._guard = guard
        self._sessions = sessions
        self._uow = uow

    def is_active(self, session_token: str) -> bool:
        return self._guard.is_active(session_token)

    def owner_of(self, session_token: str) -> int | None:
        owner = self._guard.owner(session_token)
        return owner.user_id if owner else None

    def active_count(self) -> int:
        return self._sessions.active_count()

    def describe(self, session_token: str) -> ActiveSessionView | None:
        if not self._guard.is_active(session_token):
            return None
        with self._uow() as uow:
            r = uow.session.get(PlaybackSessionRecord, session_token)
            if r is None or r.ended_at is not None:
                return None
            return ActiveSessionView(
                token=r.token,
                user_id=r.user_id,
                profile_id=r.profile_id,
                content_ref=r.content_ref,
                ip=r.ip,
                user_agent=r.user_agent,
                started_at=r.started_at,
                last_heartbeat_at=r.last_heartbeat_at,
            )

    def list_active(self, limit: int = 200) -> list[ActiveSessionView]:
        with self._uow() as uow:
            rows = (
                uow.session.execute(
                    select(PlaybackSessionRecord)
                    .where(PlaybackSessionRecord.ended_at.is_(None))
                    .order_by(PlaybackSessionRecord.started_at.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [
                ActiveSessionView(
                    token=r.token,
                    user_id=r.user_id,
                    profile_id=r.profile_id,
                    content_ref=r.content_ref,
                    ip=r.ip,
                    user_agent=r.user_agent,
                    started_at=r.started_at,
                    last_heartbeat_at=r.last_heartbeat_at,
                )
                for r in rows
                if self._guard.is_active(r.token)
            ]

    def terminate(self, session_token: str) -> bool:
        return self._sessions.release(session_token, reason="admin")
