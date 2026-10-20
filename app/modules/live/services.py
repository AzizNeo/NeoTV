"""Live channel use-cases: listing with now/next, administration, ingest, EPG."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from defusedxml import ElementTree
from sqlalchemy import and_, delete, func, or_, select

from app.kernel.db import dialect_insert, pairs
from app.kernel.security.egress import EgressGateway
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.live.api import NAMESPACE, LiveListing, LiveStats
from app.modules.live.archive import ArchiveStorage
from app.modules.live.models import LiveChannel, LiveProgram
from app.shared_kernel.events import ContentRemoved
from app.shared_kernel.ratings import KIDS_ALLOWED

MAX_XMLTV_BYTES = 50 * 1024 * 1024


class LiveError(Exception):
    pass


class LiveChannelNotFoundError(LiveError):
    pass


class InvalidIngestKeyError(LiveError):
    pass


class LiveSourceConfigError(LiveError):
    pass


class ArchiveConfigError(LiveError):
    pass


class ArchiveRightsRequiredError(LiveError):
    """Recording an external stream needs the administrator's confirmation of the rights (ADR-0012)."""


class EpgImportError(LiveError):
    pass


@dataclass(frozen=True, slots=True)
class ProgramDTO:
    id: int
    channel_id: int
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class LiveChannelDTO:
    ref: str
    id: int
    name: str
    description: str | None
    logo: str | None
    is_live: bool
    rating: str
    now: ProgramDTO | None
    next: ProgramDTO | None
    catchup_days: int = 0  # the channel's archive (ADR-0012); the viewer's plan may allow less


@dataclass(frozen=True, slots=True)
class LiveChannelAdminDTO:
    id: int
    ref: str
    name: str
    description: str | None
    logo: str | None
    source_type: str
    upstream_url: str | None
    delivery: str
    playback_id: str
    ingest_key_last4: str | None
    epg_channel_id: str | None
    rating: str
    sort_order: int
    is_live: bool
    is_active: bool
    archive_days: int = 0
    archive_confirmed_by: int | None = None
    archive_confirmed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedIngestKey:
    channel_id: int
    ingest_key: str  # shown exactly once


def _program(p: LiveProgram) -> ProgramDTO:
    return ProgramDTO(
        id=p.id,
        channel_id=p.channel_id,
        title=p.title,
        description=p.description,
        starts_at=p.starts_at,
        ends_at=p.ends_at,
    )


def _archive_off(channel: LiveChannel) -> None:
    channel.archive_days = 0
    channel.archive_confirmed_by = None
    channel.archive_confirmed_at = None


def _admin(c: LiveChannel) -> LiveChannelAdminDTO:
    return LiveChannelAdminDTO(
        id=c.id,
        ref=f"{NAMESPACE}:{c.id}",
        name=c.name,
        description=c.description,
        logo=c.logo_url,
        source_type=c.source_type,
        upstream_url=c.upstream_url,
        delivery=c.delivery,
        playback_id=c.playback_id,
        ingest_key_last4=c.ingest_key_last4,
        epg_channel_id=c.epg_channel_id,
        rating=c.rating,
        sort_order=c.sort_order,
        is_live=bool(c.is_live),
        is_active=bool(c.is_active),
        archive_days=c.archive_days or 0,
        archive_confirmed_by=c.archive_confirmed_by,
        archive_confirmed_at=c.archive_confirmed_at,
    )


class IngestKeyService:
    """Ingest keys are stored as keyed hashes; the plain key is shown once (SEC-03)."""

    def __init__(self, pepper: bytes) -> None:
        self._pepper = pepper

    def issue(self) -> tuple[str, str, str]:
        plain = secrets.token_urlsafe(24)
        return plain, self.hash(plain), plain[-4:]

    def hash(self, key: str) -> str:
        return hmac.new(self._pepper, key.encode(), hashlib.sha256).hexdigest()


class LiveChannelService:
    def __init__(self, uow: UnitOfWorkFactory, keys: IngestKeyService, clock: Clock) -> None:
        self._uow = uow
        self._keys = keys
        self._clock = clock

    # ── public ─────────────────────────────────────────────────────────────
    def list_public(self, *, kids_only: bool) -> list[LiveChannelDTO]:
        now = self._clock.now()
        with self._uow() as uow:
            stmt = select(LiveChannel).where(LiveChannel.is_active.is_(True))
            if kids_only:
                stmt = stmt.where(LiveChannel.rating.in_(sorted(KIDS_ALLOWED)))
            channels = list(uow.session.execute(stmt.order_by(LiveChannel.sort_order, LiveChannel.name)).scalars())
            schedule = self._now_next(uow.session, [c.id for c in channels], now)
            return [
                LiveChannelDTO(
                    ref=f"{NAMESPACE}:{c.id}",
                    id=c.id,
                    name=c.name,
                    description=c.description,
                    logo=c.logo_url,
                    is_live=bool(c.is_live) or c.source_type == "external",
                    rating=c.rating,
                    now=schedule.get(c.id, (None, None))[0],
                    next=schedule.get(c.id, (None, None))[1],
                    catchup_days=c.archive_days or 0,
                )
                for c in channels
            ]

    def listing(self, *, kids_only: bool) -> list[LiveListing]:
        with self._uow() as uow:
            stmt = select(LiveChannel).where(LiveChannel.is_active.is_(True))
            if kids_only:
                stmt = stmt.where(LiveChannel.rating.in_(sorted(KIDS_ALLOWED)))
            rows = uow.session.execute(stmt.order_by(LiveChannel.sort_order, LiveChannel.name, LiveChannel.id))
            return [
                LiveListing(
                    ref=f"{NAMESPACE}:{c.id}",
                    id=c.id,
                    name=c.name,
                    logo=c.logo_url,
                    rating=c.rating,
                    epg_channel_id=c.epg_channel_id,
                    added_at=c.created_at,
                )
                for c in rows.scalars()
            ]

    def archive_days(self, channel_id: int) -> int:
        """The channel's catch-up window in days (0 = not archived, or not an active channel)."""
        with self._uow() as uow:
            days = uow.session.execute(
                select(LiveChannel.archive_days).where(LiveChannel.id == channel_id, LiveChannel.is_active.is_(True))
            ).scalar_one_or_none()
            return int(days or 0)

    def get_active(self, channel_id: int) -> LiveChannel | None:
        with self._uow() as uow:
            channel = uow.session.get(LiveChannel, channel_id)
            if channel is None or not channel.is_active:
                return None
            uow.session.expunge(channel)
            return channel

    def by_playback_id(self, playback_id: str) -> LiveChannel | None:
        with self._uow() as uow:
            channel = uow.session.execute(
                select(LiveChannel).where(LiveChannel.playback_id == playback_id, LiveChannel.is_active.is_(True))
            ).scalar_one_or_none()
            if channel is not None:
                uow.session.expunge(channel)
            return channel

    @staticmethod
    def _now_next(
        session: Any, channel_ids: list[int], now: datetime
    ) -> dict[int, tuple[ProgramDTO | None, ProgramDTO | None]]:
        if not channel_ids:
            return {}
        rows = session.execute(
            select(LiveProgram)
            .where(
                LiveProgram.channel_id.in_(channel_ids),
                LiveProgram.ends_at > now,
                LiveProgram.starts_at < now + timedelta(hours=12),
            )
            .order_by(LiveProgram.channel_id, LiveProgram.starts_at)
        ).scalars()
        result: dict[int, list[ProgramDTO]] = {}
        for program in rows:
            bucket = result.setdefault(program.channel_id, [])
            if len(bucket) < 2:
                bucket.append(_program(program))
        out: dict[int, tuple[ProgramDTO | None, ProgramDTO | None]] = {}
        for cid, items in result.items():
            current = items[0] if items and items[0].starts_at <= now else None
            upcoming = items[1] if current and len(items) > 1 else (items[0] if not current and items else None)
            out[cid] = (current, upcoming)
        return out

    # ── admin ──────────────────────────────────────────────────────────────
    def list_admin(self) -> list[LiveChannelAdminDTO]:
        with self._uow() as uow:
            rows = uow.session.execute(select(LiveChannel).order_by(LiveChannel.sort_order, LiveChannel.id)).scalars()
            return [_admin(c) for c in rows]

    def create(
        self,
        *,
        name: str,
        description: str | None,
        logo: str | None,
        source_type: str,
        upstream_url: str | None,
        delivery: str,
        rating: str,
        epg_channel_id: str | None,
        sort_order: int,
    ) -> tuple[LiveChannelAdminDTO, str | None]:
        if source_type == "external" and not upstream_url:
            raise LiveSourceConfigError("external channels need an upstream URL")
        plain_key = None
        with self._uow() as uow:
            channel = LiveChannel(
                name=name,
                description=description,
                logo_url=logo,
                source_type=source_type,
                upstream_url=upstream_url if source_type == "external" else None,
                delivery=delivery if source_type == "external" else "proxy",
                playback_id=secrets.token_hex(12),
                rating=rating,
                epg_channel_id=epg_channel_id,
                sort_order=sort_order,
                is_live=False,
                is_active=True,
            )
            if source_type == "ingest":
                plain_key, key_hash, last4 = self._keys.issue()
                channel.ingest_key_hash, channel.ingest_key_last4 = key_hash, last4
            uow.session.add(channel)
            uow.session.flush([channel])
            dto = _admin(channel)
        return dto, plain_key

    def update(self, channel_id: int, **changes: Any) -> LiveChannelAdminDTO:
        allowed = {
            "name",
            "description",
            "logo_url",
            "upstream_url",
            "delivery",
            "rating",
            "epg_channel_id",
            "sort_order",
            "is_active",
        }
        with self._uow() as uow:
            channel = uow.session.get(LiveChannel, channel_id)
            if channel is None:
                raise LiveChannelNotFoundError("Live channel not found")
            previous_source = channel.upstream_url
            for field, value in changes.items():
                if field in allowed and value is not None:
                    setattr(channel, field, value)
            if channel.source_type == "external" and not channel.upstream_url:
                raise LiveSourceConfigError("external channels need an upstream URL")
            if channel.source_type == "external" and channel.upstream_url != previous_source:
                # The right to record was confirmed for the old stream, not for this one (ADR-0012).
                _archive_off(channel)
            return _admin(channel)

    def set_archive(
        self, channel_id: int, *, days: int, rights_confirmed: bool, actor_id: int, max_days: int
    ) -> LiveChannelAdminDTO:
        """Switch a channel's catch-up archive on (``days`` > 0) or off (0)."""
        if not 0 <= days <= max_days:
            raise ArchiveConfigError(f"archive days must be between 0 and {max_days}")
        with self._uow() as uow:
            channel = uow.session.get(LiveChannel, channel_id)
            if channel is None:
                raise LiveChannelNotFoundError("Live channel not found")
            if days == 0:
                _archive_off(channel)
                return _admin(channel)
            if channel.source_type == "external" and not rights_confirmed:
                raise ArchiveRightsRequiredError("confirm that the operator may record this external stream")
            channel.archive_days = days
            channel.archive_confirmed_by = actor_id
            channel.archive_confirmed_at = self._clock.now()
            return _admin(channel)

    def rotate_ingest_key(self, channel_id: int) -> IssuedIngestKey:
        with self._uow() as uow:
            channel = uow.session.get(LiveChannel, channel_id)
            if channel is None or channel.source_type != "ingest":
                raise LiveChannelNotFoundError("Ingest channel not found")
            plain, key_hash, last4 = self._keys.issue()
            channel.ingest_key_hash, channel.ingest_key_last4 = key_hash, last4
        return IssuedIngestKey(channel_id=channel_id, ingest_key=plain)

    def remove(self, channel_id: int) -> None:
        with self._uow() as uow:
            channel = uow.session.get(LiveChannel, channel_id)
            if channel is None or not channel.is_active:
                raise LiveChannelNotFoundError("Live channel not found")
            channel.is_active = False
            channel.is_live = False
            uow.outbox.add(
                ContentRemoved(content_ref=f"{NAMESPACE}:{channel.id}", occurred_at=self._clock.now().isoformat())
            )

    def stats(self, transcoding: int) -> LiveStats:
        with self._uow() as uow:
            total = int(
                uow.session.execute(
                    select(func.count(LiveChannel.id)).where(LiveChannel.is_active.is_(True))
                ).scalar_one()
            )
            on_air = int(
                uow.session.execute(
                    select(func.count(LiveChannel.id)).where(
                        LiveChannel.is_active.is_(True),
                        or_(LiveChannel.source_type == "external", LiveChannel.is_live.is_(True)),
                    )
                ).scalar_one()
            )
        return LiveStats(channels=total, on_air=on_air, transcoding=transcoding)

    # ── ingest (nginx-rtmp callbacks) ─────────────────────────────────────
    def on_publish(self, presented_key: str) -> str:
        """Verify an RTMP publish key; returns the public playback id the stream is renamed to."""
        key_hash = self._keys.hash(presented_key)
        with self._uow() as uow:
            channel = uow.session.execute(
                select(LiveChannel).where(
                    LiveChannel.ingest_key_hash == key_hash,
                    LiveChannel.source_type == "ingest",
                    LiveChannel.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if channel is None:
                raise InvalidIngestKeyError("unknown ingest key")
            channel.is_live = True
            channel.started_at = self._clock.now()
            return channel.playback_id

    def on_done(self, playback_id: str) -> None:
        with self._uow() as uow:
            channel = uow.session.execute(
                select(LiveChannel).where(LiveChannel.playback_id == playback_id)
            ).scalar_one_or_none()
            if channel is not None:
                channel.is_live = False


class EpgService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def guide(self, *, start: datetime, end: datetime, channel_ids: list[int] | None = None) -> list[ProgramDTO]:
        with self._uow() as uow:
            stmt = select(LiveProgram).where(and_(LiveProgram.ends_at > start, LiveProgram.starts_at < end))
            if channel_ids:
                stmt = stmt.where(LiveProgram.channel_id.in_(channel_ids))
            return [
                _program(p)
                for p in uow.session.execute(stmt.order_by(LiveProgram.channel_id, LiveProgram.starts_at)).scalars()
            ]

    def add(
        self, *, channel_id: int, title: str, description: str | None, starts_at: datetime, ends_at: datetime
    ) -> ProgramDTO:
        if ends_at <= starts_at:
            raise EpgImportError("program must end after it starts")
        with self._uow() as uow:
            if uow.session.get(LiveChannel, channel_id) is None:
                raise LiveChannelNotFoundError("Live channel not found")
            program = LiveProgram(
                channel_id=channel_id, title=title, description=description, starts_at=starts_at, ends_at=ends_at
            )
            uow.session.add(program)
            uow.session.flush([program])
            return _program(program)

    def delete(self, program_id: int) -> None:
        with self._uow() as uow:
            uow.session.execute(delete(LiveProgram).where(LiveProgram.id == program_id))

    def import_xmltv(self, egress: EgressGateway, url: str, *, horizon_days: int = 3) -> dict[str, int]:
        response = egress.get(url, stream=True)
        if response.status_code != 200:
            response.close()
            raise EpgImportError(f"XMLTV source returned HTTP {response.status_code}")
        raw = EgressGateway.read_capped(response, MAX_XMLTV_BYTES)
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            raise EpgImportError(f"invalid XMLTV: {exc}") from exc
        now = self._clock.now()
        horizon = now + timedelta(days=horizon_days)
        with self._uow() as uow:
            mapping = pairs(
                uow.session.execute(
                    select(LiveChannel.epg_channel_id, LiveChannel.id).where(LiveChannel.epg_channel_id.is_not(None))
                ).all()
            )
            rows: list[dict[str, Any]] = []
            for element in root.iter("programme"):
                channel_id = mapping.get(element.get("channel"))
                if channel_id is None:
                    continue
                try:
                    starts, ends = _xmltv_time(element.get("start", "")), _xmltv_time(element.get("stop", ""))
                except ValueError:
                    continue
                if ends <= now - timedelta(hours=6) or starts > horizon or ends <= starts:
                    continue
                rows.append(
                    {
                        "channel_id": channel_id,
                        "title": (element.findtext("title") or "Untitled")[:200],
                        "description": (element.findtext("desc") or None) and element.findtext("desc")[:1000],
                        "starts_at": starts,
                        "ends_at": ends,
                    }
                )
            for start_index in range(0, len(rows), 500):
                stmt = dialect_insert(uow.session, LiveProgram.__table__)
                batch = rows[start_index : start_index + 500]
                uow.session.execute(
                    stmt.values(batch).on_conflict_do_update(
                        index_elements=["channel_id", "starts_at"],
                        set_={
                            "title": stmt.excluded.title,
                            "description": stmt.excluded.description,
                            "ends_at": stmt.excluded.ends_at,
                        },
                    )
                )
            pruned = uow.session.execute(
                delete(LiveProgram).where(LiveProgram.ends_at < now - timedelta(days=2))
            ).rowcount
        return {"imported": len(rows), "pruned": int(pruned or 0), "mapped_channels": len(mapping)}


def _xmltv_time(value: str) -> datetime:
    """XMLTV: 'YYYYmmddHHMMSS +HHMM' (offset optional → UTC)."""
    value = value.strip()
    if " " in value:
        stamp, offset = value.split(" ", 1)
        return datetime.strptime(f"{stamp} {offset}", "%Y%m%d%H%M%S %z")
    return datetime.strptime(value[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ArchivedChannel:
    id: int
    days: int
    since: datetime | None  # when the archive was switched on


@dataclass(frozen=True, slots=True)
class RecordingSource:
    url: str
    external: bool  # an operator-entered URL on the internet: checked by the egress policy


class ArchiveService:
    """Which channels are archived, and the retention that keeps each to its window (ADR-0012)."""

    def __init__(self, uow: UnitOfWorkFactory, storage: ArchiveStorage, clock: Clock, *, rtmp_base: str = "") -> None:
        self._uow = uow
        self._storage = storage
        self._clock = clock
        self._rtmp_base = rtmp_base.rstrip("/")

    def recording_sources(self) -> dict[int, RecordingSource]:
        """What the recorder should record right now: archived channels whose source is up.

        External: the upstream URL (the recorder checks it with the egress policy first). Ingest:
        the internal RTMP stream, only while the encoder is connected (``is_live``) — otherwise
        there is nothing to pull and the archive simply has a gap.
        """
        with self._uow() as uow:
            rows = uow.session.execute(
                select(LiveChannel).where(LiveChannel.archive_days > 0, LiveChannel.is_active.is_(True))
            ).scalars()
            sources: dict[int, RecordingSource] = {}
            for channel in rows:
                if channel.source_type == "external" and channel.upstream_url:
                    sources[channel.id] = RecordingSource(channel.upstream_url, external=True)
                elif channel.source_type == "ingest" and channel.is_live and self._rtmp_base:
                    sources[channel.id] = RecordingSource(f"{self._rtmp_base}/{channel.playback_id}", external=False)
            return sources

    def archived(self) -> list[ArchivedChannel]:
        with self._uow() as uow:
            rows = uow.session.execute(
                select(LiveChannel.id, LiveChannel.archive_days, LiveChannel.archive_confirmed_at).where(
                    LiveChannel.archive_days > 0, LiveChannel.is_active.is_(True)
                )
            )
            return [ArchivedChannel(id=i, days=d, since=s) for i, d, s in rows]

    def enforce_retention(self) -> dict[str, int]:
        """Deletes what is older than each channel's window, and everything of a channel no longer
        archived (switched off, deactivated or removed). Never runs in the playback path."""
        now = self._clock.now()
        windows = {c.id: c.days for c in self.archived()}
        removed = trimmed = dropped = 0
        for channel_id in self._storage.channels():
            days = windows.get(channel_id)
            if days is None:
                removed += self._storage.delete_channel(channel_id)
                dropped += 1
            else:
                count = self._storage.delete_before(channel_id, now - timedelta(days=days))
                removed += count
                trimmed += 1 if count else 0
        return {"segments_removed": removed, "channels_trimmed": trimmed, "channels_dropped": dropped}

    def lag_seconds(self) -> dict[int, float]:
        """Per archived channel: seconds since its newest segment began (since switch-on if none)."""
        now = self._clock.now()
        out: dict[int, float] = {}
        for channel in self.archived():
            newest = self._storage.newest(channel.id) or channel.since or now
            out[channel.id] = max(0.0, (now - newest).total_seconds())
        return out
