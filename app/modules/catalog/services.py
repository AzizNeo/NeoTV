"""Catalog use-cases: browsing, administration, playlist synchronisation."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.kernel.db import dialect_insert, pairs
from app.kernel.resilience.best_effort import best_effort
from app.kernel.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitOpenError
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.catalog.api import NAMESPACE, CatalogStats
from app.modules.catalog.models import Channel, Playlist
from app.modules.catalog.parsing import ParsedEntry
from app.shared_kernel.events import ContentRemoved
from app.shared_kernel.ratings import KIDS_ALLOWED

_log = logging.getLogger("catalog")

SYSTEM_PLAYLIST_MANUAL = "Manual"
SNAPSHOT_KEY = "catalog:snapshot:page1:v2"
SNAPSHOT_TTL = 24 * 3600


class CatalogError(Exception):
    pass


class ChannelNotFoundError(CatalogError):
    pass


class PlaylistNotFoundError(CatalogError):
    pass


class SystemPlaylistProtectedError(CatalogError):
    pass


class DuplicateChannelError(CatalogError):
    pass


# ── DTOs ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ChannelCardDTO:
    ref: str
    id: int
    name: str
    logo: str | None
    group: str
    kind: str
    rating: str


@dataclass(frozen=True, slots=True)
class ChannelPage:
    items: list[ChannelCardDTO]
    total: int
    page: int
    per_page: int
    pages: int
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class ChannelAdminDTO:
    id: int
    ref: str
    playlist_id: int
    name: str
    stream_url: str
    logo: str | None
    group: str
    kind: str
    rating: str
    delivery: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class PlaylistDTO:
    id: int
    name: str
    is_system: bool
    has_source: bool
    channel_count: int
    last_synced_at: Any
    last_sync_status: str | None
    last_sync_error: str | None


@dataclass(frozen=True, slots=True)
class SyncReport:
    playlist_id: int
    upserted: int
    deactivated: int
    skipped_dead: int


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    page: int = 1
    per_page: int = 24
    search: str | None = None
    group: str | None = None
    kind: str | None = None
    kids_only: bool = False

    @property
    def is_snapshot_eligible(self) -> bool:
        return self.page == 1 and not (self.search or self.group or self.kind or self.kids_only)


def card(channel: Channel) -> ChannelCardDTO:
    return ChannelCardDTO(
        ref=f"{NAMESPACE}:{channel.id}",
        id=channel.id,
        name=channel.name,
        logo=channel.logo_url,
        group=channel.group_name,
        kind=channel.kind,
        rating=channel.rating,
    )


def admin_view(channel: Channel) -> ChannelAdminDTO:
    return ChannelAdminDTO(
        id=channel.id,
        ref=f"{NAMESPACE}:{channel.id}",
        playlist_id=channel.playlist_id,
        name=channel.name,
        stream_url=channel.stream_url,
        logo=channel.logo_url,
        group=channel.group_name,
        kind=channel.kind,
        rating=channel.rating,
        delivery=channel.delivery,
        is_active=bool(channel.is_active),
    )


# ── Repository ──────────────────────────────────────────────────────────────
class ChannelRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, channel_id: int) -> Channel | None:
        return self._s.get(Channel, channel_id)

    def active(self, channel_id: int) -> Channel | None:
        channel = self._s.get(Channel, channel_id)
        return channel if channel is not None and channel.is_active else None

    def by_ids(self, ids: list[int]) -> list[Channel]:
        if not ids:
            return []
        return list(self._s.execute(select(Channel).where(Channel.id.in_(ids), Channel.is_active.is_(True))).scalars())

    def page(self, q: CatalogQuery) -> tuple[list[Channel], int]:
        stmt = select(Channel).where(Channel.is_active.is_(True))
        if q.search:
            stmt = stmt.where(func.lower(Channel.name).like(f"%{q.search.strip().lower()}%"))
        if q.group:
            stmt = stmt.where(Channel.group_name == q.group)
        if q.kind:
            stmt = stmt.where(Channel.kind == q.kind)
        if q.kids_only:
            stmt = stmt.where(Channel.rating.in_(sorted(KIDS_ALLOWED)))
        total = int(self._s.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
        rows = self._s.execute(
            stmt.order_by(Channel.group_name, Channel.name, Channel.id)
            .offset((q.page - 1) * q.per_page)
            .limit(q.per_page)
        ).scalars()
        return list(rows), total

    def groups(self, *, kids_only: bool) -> list[tuple[str, int]]:
        stmt = select(Channel.group_name, func.count(Channel.id)).where(Channel.is_active.is_(True))
        if kids_only:
            stmt = stmt.where(Channel.rating.in_(sorted(KIDS_ALLOWED)))
        stmt = stmt.group_by(Channel.group_name).order_by(func.count(Channel.id).desc(), Channel.group_name)
        return [(g, int(n)) for g, n in self._s.execute(stmt)]

    def similar(self, channel_id: int, limit: int) -> list[Channel]:
        source = self.active(channel_id)
        if source is None:
            return []
        return list(
            self._s.execute(
                select(Channel)
                .where(Channel.group_name == source.group_name, Channel.id != channel_id, Channel.is_active.is_(True))
                .order_by(Channel.name)
                .limit(limit)
            ).scalars()
        )

    def by_groups(self, groups: list[str], exclude_ids: list[int], limit: int) -> list[Channel]:
        if not groups:
            return []
        stmt = select(Channel).where(Channel.group_name.in_(groups), Channel.is_active.is_(True))
        if exclude_ids:
            stmt = stmt.where(Channel.id.not_in(exclude_ids))
        return list(self._s.execute(stmt.order_by(Channel.name).limit(limit)).scalars())

    def stats(self) -> CatalogStats:
        rows = pairs(
            self._s.execute(
                select(Channel.kind, func.count(Channel.id)).where(Channel.is_active.is_(True)).group_by(Channel.kind)
            ).all()
        )
        playlists = int(self._s.execute(select(func.count(Playlist.id))).scalar_one())
        live, vod = int(rows.get("live", 0)), int(rows.get("vod", 0))
        return CatalogStats(channels=live + vod, live=live, vod=vod, playlists=playlists)

    def system_playlist(self, name: str = SYSTEM_PLAYLIST_MANUAL) -> Playlist:
        playlist = self._s.execute(
            select(Playlist).where(Playlist.is_system.is_(True), Playlist.name == name)
        ).scalar_one_or_none()
        if playlist is None:
            playlist = Playlist(name=name, is_system=True)
            self._s.add(playlist)
            self._s.flush([playlist])
        return playlist

    def upsert(self, playlist_id: int, rows: list[dict[str, Any]], now: Any) -> None:
        if not rows:
            return
        stmt = dialect_insert(self._s, Channel.__table__)
        excluded = stmt.excluded
        self._s.execute(
            stmt.values(
                [
                    {**r, "playlist_id": playlist_id, "is_active": True, "created_at": now, "updated_at": now}
                    for r in rows
                ]
            ).on_conflict_do_update(
                index_elements=["playlist_id", "source_key"],
                set_={
                    "name": excluded.name,
                    "stream_url": excluded.stream_url,
                    "logo_url": excluded.logo_url,
                    "group_name": excluded.group_name,
                    "kind": excluded.kind,
                    "is_active": True,
                    "updated_at": now,
                },
            )
        )

    def deactivate_missing(self, playlist_id: int, keep_keys: set[str]) -> list[int]:
        active = self._s.execute(
            select(Channel.id, Channel.source_key).where(
                Channel.playlist_id == playlist_id, Channel.is_active.is_(True)
            )
        ).all()
        stale = [cid for cid, key in active if key not in keep_keys]
        for start in range(0, len(stale), 500):
            self._s.execute(update(Channel).where(Channel.id.in_(stale[start : start + 500])).values(is_active=False))
        return stale


# ── Query service (user-facing browsing) ────────────────────────────────────
class CatalogQueryService:
    def __init__(self, uow: UnitOfWorkFactory, breakers: CircuitBreakerRegistry, redis: Any) -> None:
        self._uow = uow
        self._breaker = breakers.get(
            "catalog.db", failure_threshold=5, recovery_timeout=30, counted=(_DatabaseFailure,)
        )
        self._redis = redis

    def page(self, q: CatalogQuery) -> ChannelPage:
        try:
            result = self._breaker.call(lambda: self._page_from_db(q))
        except (CircuitOpenError, _DatabaseFailure) as exc:  # only the DB failure domain degrades (RT-09)
            _log.warning("catalog.degraded reason=%s", type(exc).__name__)
            snapshot = best_effort(lambda: self._redis.get(SNAPSHOT_KEY), op="catalog.snapshot.read")
            if snapshot:
                data = json.loads(snapshot)
                return ChannelPage(
                    items=[ChannelCardDTO(**i) for i in data["items"]],
                    total=data["total"],
                    page=1,
                    per_page=data["per_page"],
                    pages=data["pages"],
                    degraded=True,
                )
            return ChannelPage(items=[], total=0, page=q.page, per_page=q.per_page, pages=0, degraded=True)
        if q.is_snapshot_eligible:
            payload = json.dumps(asdict(result), default=str)
            best_effort(lambda: self._redis.set(SNAPSHOT_KEY, payload, ex=SNAPSHOT_TTL), op="catalog.snapshot.write")
        return result

    def _page_from_db(self, q: CatalogQuery) -> ChannelPage:
        from sqlalchemy.exc import SQLAlchemyError

        try:
            with self._uow() as uow:
                rows, total = ChannelRepository(uow.session).page(q)
                items = [card(c) for c in rows]
        except SQLAlchemyError as exc:
            raise _DatabaseFailure(str(exc)) from exc
        pages = math.ceil(total / q.per_page) if total else 0
        return ChannelPage(items=items, total=total, page=q.page, per_page=q.per_page, pages=pages)

    def groups(self, *, kids_only: bool) -> list[tuple[str, int]]:
        with self._uow() as uow:
            return ChannelRepository(uow.session).groups(kids_only=kids_only)

    def similar(self, channel_id: int, limit: int, *, kids_only: bool) -> list[ChannelCardDTO]:
        with self._uow() as uow:
            items = [card(c) for c in ChannelRepository(uow.session).similar(channel_id, limit)]
        return [i for i in items if not kids_only or i.rating in KIDS_ALLOWED]

    def get(self, channel_id: int, *, kids_only: bool) -> ChannelCardDTO:
        with self._uow() as uow:
            channel = ChannelRepository(uow.session).active(channel_id)
            if channel is None or (kids_only and channel.rating not in KIDS_ALLOWED):
                raise ChannelNotFoundError("Channel not found")
            return card(channel)


class _DatabaseFailure(RuntimeError):
    """Only database failures count against the catalog breaker (RT-09)."""


# ── Reader (capability catalog.read) ────────────────────────────────────────
class CatalogReaderService:
    def __init__(self, uow: UnitOfWorkFactory) -> None:
        self._uow = uow

    def similar(self, channel_id: int, limit: int) -> list[int]:
        with self._uow() as uow:
            return [c.id for c in ChannelRepository(uow.session).similar(channel_id, limit)]

    def by_groups(self, groups: list[str], *, exclude_ids: list[int], limit: int) -> list[int]:
        with self._uow() as uow:
            return [c.id for c in ChannelRepository(uow.session).by_groups(groups, exclude_ids, limit)]

    def groups_of(self, channel_ids: list[int]) -> dict[int, str]:
        with self._uow() as uow:
            return {c.id: c.group_name for c in ChannelRepository(uow.session).by_ids(channel_ids)}

    def stats(self) -> CatalogStats:
        with self._uow() as uow:
            return ChannelRepository(uow.session).stats()


# ── Administration ──────────────────────────────────────────────────────────
class CatalogAdminService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def list_channels(
        self, *, page: int, per_page: int, search: str | None, include_inactive: bool
    ) -> tuple[list[ChannelAdminDTO], int]:
        with self._uow() as uow:
            stmt = select(Channel)
            if not include_inactive:
                stmt = stmt.where(Channel.is_active.is_(True))
            if search:
                like = f"%{search.strip().lower()}%"
                stmt = stmt.where(or_(func.lower(Channel.name).like(like), func.lower(Channel.group_name).like(like)))
            total = int(uow.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
            rows = uow.session.execute(
                stmt.order_by(Channel.id.desc()).offset((page - 1) * per_page).limit(per_page)
            ).scalars()
            return [admin_view(c) for c in rows], total

    def add_channel(
        self, *, name: str, stream_url: str, logo: str | None, group: str, kind: str, rating: str, delivery: str
    ) -> ChannelAdminDTO:
        with self._uow() as uow:
            repo = ChannelRepository(uow.session)
            playlist = repo.system_playlist()
            key = "url:" + hashlib.sha1(stream_url.strip().encode(), usedforsecurity=False).hexdigest()
            existing = uow.session.execute(
                select(Channel).where(Channel.playlist_id == playlist.id, Channel.source_key == key)
            ).scalar_one_or_none()
            if existing is not None and existing.is_active:
                raise DuplicateChannelError("This stream URL already exists in the catalog")
            now = self._clock.now()
            repo.upsert(
                playlist.id,
                [
                    {
                        "source_key": key,
                        "name": name,
                        "stream_url": stream_url,
                        "logo_url": logo,
                        "group_name": group,
                        "kind": kind,
                    }
                ],
                now,
            )
            channel = uow.session.execute(
                select(Channel).where(Channel.playlist_id == playlist.id, Channel.source_key == key)
            ).scalar_one()
            channel.rating = rating
            channel.delivery = delivery
            return admin_view(channel)

    def update_channel(self, channel_id: int, **changes: Any) -> ChannelAdminDTO:
        allowed = {"name", "logo_url", "group_name", "kind", "rating", "delivery"}
        with self._uow() as uow:
            channel = ChannelRepository(uow.session).get(channel_id)
            if channel is None:
                raise ChannelNotFoundError("Channel not found")
            for field, value in changes.items():
                if field in allowed and value is not None:
                    setattr(channel, field, value)
            channel.updated_at = self._clock.now()
            return admin_view(channel)

    def remove_channel(self, channel_id: int) -> None:
        with self._uow() as uow:
            channel = ChannelRepository(uow.session).get(channel_id)
            if channel is None or not channel.is_active:
                raise ChannelNotFoundError("Channel not found")
            channel.is_active = False
            uow.outbox.add(
                ContentRemoved(content_ref=f"{NAMESPACE}:{channel.id}", occurred_at=self._clock.now().isoformat())
            )

    # playlists
    def list_playlists(self) -> list[PlaylistDTO]:
        with self._uow() as uow:
            counts = pairs(
                uow.session.execute(
                    select(Channel.playlist_id, func.count(Channel.id))
                    .where(Channel.is_active.is_(True))
                    .group_by(Channel.playlist_id)
                ).all()
            )
            playlists = uow.session.execute(select(Playlist).order_by(Playlist.id)).scalars()
            return [
                PlaylistDTO(
                    id=p.id,
                    name=p.name,
                    is_system=bool(p.is_system),
                    has_source=bool(p.source_url),
                    channel_count=int(counts.get(p.id, 0)),
                    last_synced_at=p.last_synced_at,
                    last_sync_status=p.last_sync_status,
                    last_sync_error=p.last_sync_error,
                )
                for p in playlists
            ]

    def create_playlist(self, *, name: str, source_url: str | None, created_by: int) -> int:
        with self._uow() as uow:
            playlist = Playlist(name=name, source_url=source_url, is_system=False, created_by=created_by)
            uow.session.add(playlist)
            uow.session.flush([playlist])
            return playlist.id

    def delete_playlist(self, playlist_id: int) -> None:
        with self._uow() as uow:
            playlist = uow.session.get(Playlist, playlist_id)
            if playlist is None:
                raise PlaylistNotFoundError("Playlist not found")
            if playlist.is_system:
                raise SystemPlaylistProtectedError("System playlists cannot be deleted")
            refs = (
                uow.session.execute(
                    select(Channel.id).where(Channel.playlist_id == playlist_id, Channel.is_active.is_(True))
                )
                .scalars()
                .all()
            )
            now = self._clock.now().isoformat()
            for channel_id in refs:
                uow.outbox.add(ContentRemoved(content_ref=f"{NAMESPACE}:{channel_id}", occurred_at=now))
            uow.session.delete(playlist)

    def playlist_source(self, playlist_id: int) -> str | None:
        with self._uow() as uow:
            playlist = uow.session.get(Playlist, playlist_id)
            if playlist is None:
                raise PlaylistNotFoundError("Playlist not found")
            return playlist.source_url

    def manual_playlist_id(self) -> int:
        with self._uow() as uow:
            return ChannelRepository(uow.session).system_playlist().id


# ── Synchronisation ─────────────────────────────────────────────────────────
class PlaylistSyncService:
    BATCH = 500

    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def sync(
        self,
        playlist_id: int,
        entries: list[ParsedEntry],
        kinds: dict[str, str] | None = None,
        *,
        replace: bool,
    ) -> SyncReport:
        """Upsert by natural key (playlist_id, source_key) — channel ids are STABLE across refreshes,
        so favourites/progress/DRM keep pointing at the right rows (DATA-06). ``replace`` deactivates
        entries no longer present (full refresh); imports into an existing bucket use replace=False."""
        kinds = kinds or {}
        now = self._clock.now()
        with self._uow() as uow:
            playlist = uow.session.get(Playlist, playlist_id)
            if playlist is None:
                raise PlaylistNotFoundError("Playlist not found")
            repo = ChannelRepository(uow.session)
            rows: list[dict[str, Any]] = []
            dead = 0
            for entry in entries:
                kind = kinds.get(entry.url) or entry.kind_hint or "live"
                if kind == "dead":
                    dead += 1
                    continue
                rows.append(
                    {
                        "source_key": entry.source_key,
                        "name": entry.name,
                        "stream_url": entry.url,
                        "logo_url": entry.logo,
                        "group_name": (entry.group or "Uncategorized")[:128],
                        "kind": "vod" if kind == "vod" else "live",
                        "rating": entry.rating_hint,
                    }
                )
            for start in range(0, len(rows), self.BATCH):
                repo.upsert(playlist_id, rows[start : start + self.BATCH], now)
            removed: list[int] = []
            if replace:
                removed = repo.deactivate_missing(playlist_id, {r["source_key"] for r in rows})
                for channel_id in removed:
                    uow.outbox.add(ContentRemoved(content_ref=f"{NAMESPACE}:{channel_id}", occurred_at=now.isoformat()))
            playlist.last_synced_at = now
            playlist.last_sync_status = "ok"
            playlist.last_sync_error = None
        return SyncReport(playlist_id=playlist_id, upserted=len(rows), deactivated=len(removed), skipped_dead=dead)

    def mark_failed(self, playlist_id: int, error: str) -> None:
        with self._uow() as uow:
            playlist = uow.session.get(Playlist, playlist_id)
            if playlist is not None:
                playlist.last_sync_status = "failed"
                playlist.last_sync_error = error[:500]
                playlist.last_synced_at = self._clock.now()
