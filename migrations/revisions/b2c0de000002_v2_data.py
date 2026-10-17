"""v2 data: copy and transform the legacy rows into the modular tables

Revision ID: b2c0de000002
Revises: b2c0de000001
Create Date: 2026-10-09

Migrate step of the expand / migrate / contract cut-over. Nothing legacy is
modified or dropped here (that is b2c0de000003), so a failed or suspicious
run can be inspected against the untouched source tables.

Design rules:
* SQLAlchemy Core with table definitions frozen *in this file* — application
  models will change, this revision must not.
* Portable (SQLite and PostgreSQL); streaming reads, batched writes.
* Identifiers that other data points at are preserved (users, playlists,
  catalog channels, live channels) so ``catalog:<id>`` / ``live:<id>`` content
  refs keep meaning the same thing. PostgreSQL sequences are re-aligned.
* Legacy timestamps are naive UTC (``datetime.utcnow``) → made aware UTC.

Deliberate non-migrations (also in docs/adr/0010-from-audit-to-rewrite.md):
* Refresh tokens / web sessions: v2 auth is new; everyone signs in again.
* Device fingerprints: v2 device keys are HMAC(pepper, …) and cannot be
  recomputed here; legacy devices are kept as *inactive* history rows.
* RTMP ingest keys: v2 stores HMAC hashes; legacy plaintext keys are NOT
  carried over — rotate them from the admin panel (external sources keep
  working unchanged).
* DRM content keys: legacy keys were stored and served in clear (SEC-07) and
  must be considered compromised; protection is re-applied with fresh,
  envelope-encrypted keys. DRM policies are migrated.
* access_log / background_job: operational noise, not migrated.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "b2c0de000002"
down_revision = "b2c0de000001"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.v2_data")

BATCH = 1000
NOW = datetime.now(UTC)
DEFAULT_PROFILE_NAME = "Ana Profil"
MANUAL_PLAYLIST = "Manual"
UNUSABLE_PASSWORD = "!legacy-account-without-password"
PLANS = {"free", "personal", "duo", "family"}
PLAN_ALIASES = {
    "enterprise": "family",
    "premium": "family",
    "basic": "personal",
    "standard": "duo",
}
STATUSES = {"trial", "active", "grace", "cancelled", "expired", "suspended"}
VOD_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")
VOD_GROUP_HINTS = ("movie", "film", "sinema", "vod", "dizi", "series")
ADULT_HINTS = ("adult", "xxx", "18+", "+18", "yetiskin", "yetişkin", "erotic")
KIDS_HINTS = ("kids", "çocuk", "cocuk", "cartoon", "çizgi", "cizgi", "children")
RESOLUTIONS = ("240p", "360p", "480p", "720p", "1080p", "1440p", "2160p")
DEVICE_CLASSES = {"desktop", "mobile", "tablet", "tv", "unknown"}

_ts = sa.DateTime()
_tstz = sa.DateTime(timezone=True)


def _t(name: str, *cols: tuple[str, Any]) -> sa.TableClause:
    return sa.table(name, *(sa.column(c, typ) for c, typ in cols))


# ── Frozen table shapes ────────────────────────────────────────────────────
# legacy
L_USER = _t(
    "user",
    ("id", sa.Integer),
    ("username", sa.String),
    ("password_hash", sa.String),
    ("role", sa.String),
    ("created_at", _ts),
    ("subscription_plan", sa.String),
    ("is_active", sa.Boolean),
    ("expire_date", _ts),
    ("last_ip", sa.String),
    ("last_login", _ts),
)
L_PLAYLIST = _t(
    "playlist",
    ("id", sa.Integer),
    ("name", sa.String),
    ("url", sa.String),
    ("created_at", _ts),
    ("updated_at", _ts),
)
L_CHANNEL = _t(
    "channel",
    ("id", sa.Integer),
    ("name", sa.String),
    ("url", sa.String),
    ("logo", sa.String),
    ("group", sa.String),
    ("playlist_id", sa.Integer),
)
L_LIVE = _t(
    "live_channel",
    ("id", sa.Integer),
    ("name", sa.String),
    ("description", sa.String),
    ("logo", sa.String),
    ("hls_url", sa.String),
    ("started_at", _ts),
)
L_EPG = _t(
    "legacy_live_epg",
    ("live_channel_id", sa.Integer),
    ("program_name", sa.String),
    ("description", sa.String),
    ("start_time", _ts),
    ("end_time", _ts),
)
L_DEVICE = _t(
    "device",
    ("user_id", sa.Integer),
    ("device_id", sa.String),
    ("device_name", sa.String),
    ("device_type", sa.String),
    ("browser", sa.String),
    ("os", sa.String),
    ("is_trusted", sa.Boolean),
    ("last_seen", _ts),
    ("last_ip", sa.String),
    ("login_count", sa.Integer),
    ("created_at", _ts),
)
L_SUB = _t(
    "subscription",
    ("user_id", sa.Integer),
    ("plan", sa.String),
    ("status", sa.String),
    ("started_at", _ts),
    ("expires_at", _ts),
    ("trial_ends_at", _ts),
    ("grace_ends_at", _ts),
    ("cancelled_at", _ts),
    ("billing_cycle", sa.String),
    ("auto_renew", sa.Boolean),
    ("payment_provider", sa.String),
    ("external_subscription_id", sa.String),
    ("created_at", _ts),
    ("updated_at", _ts),
)
L_FAVORITE = _t(
    "favorite", ("user_id", sa.Integer), ("channel_id", sa.Integer), ("created_at", _ts)
)
L_PROGRESS = _t(
    "watch_progress",
    ("user_id", sa.Integer),
    ("channel_id", sa.Integer),
    ("last_position", sa.Integer),
    ("total_duration", sa.Integer),
    ("is_completed", sa.Boolean),
    ("created_at", _ts),
    ("updated_at", _ts),
)
L_HISTORY = _t(
    "watch_history",
    ("user_id", sa.Integer),
    ("channel_id", sa.Integer),
    ("timestamp", _ts),
    ("duration", sa.Integer),
)
L_SESSION = _t(
    "stream_session",
    ("user_id", sa.Integer),
    ("token", sa.String),
    ("channel_id", sa.Integer),
    ("ip_address", sa.String),
    ("user_agent", sa.String),
    ("started_at", _ts),
    ("last_heartbeat", _ts),
    ("expires_at", _ts),
)
L_EVENT = _t(
    "playback_event",
    ("user_id", sa.Integer),
    ("channel_id", sa.Integer),
    ("event_type", sa.String),
    ("position", sa.Integer),
    ("session_token", sa.String),
    ("created_at", _ts),
)
L_METRICS = _t(
    "playback_metrics",
    ("user_id", sa.Integer),
    ("channel_id", sa.Integer),
    ("session_token", sa.String),
    ("startup_time_ms", sa.Integer),
    ("rebuffer_count", sa.Integer),
    ("rebuffer_duration_ms", sa.Integer),
    ("watch_duration_seconds", sa.Integer),
    ("device_type", sa.String),
    ("resolution", sa.String),
    ("connection_type", sa.String),
    ("created_at", _ts),
)
L_DRM_POLICY = _t(
    "drm_policy",
    ("name", sa.String),
    ("max_resolution", sa.String),
    ("allow_offline", sa.Boolean),
    ("offline_validity_hours", sa.Integer),
    ("allowed_device_types", sa.String),
    ("require_hdcp", sa.Boolean),
    ("allow_screen_capture", sa.Boolean),
    ("license_duration_seconds", sa.Integer),
    ("created_at", _ts),
)
L_DRM_CONTENT = _t("drm_content", ("id", sa.Integer))

# v2
USERS = _t(
    "identity_users",
    ("id", sa.Integer),
    ("username", sa.String),
    ("email", sa.String),
    ("password_hash", sa.String),
    ("role", sa.String),
    ("is_active", sa.Boolean),
    ("token_version", sa.Integer),
    ("created_at", _tstz),
    ("last_login_at", _tstz),
    ("last_login_ip", sa.String),
)
PROFILES = _t(
    "profiles",
    ("id", sa.Integer),
    ("user_id", sa.Integer),
    ("name", sa.String),
    ("avatar", sa.String),
    ("is_kids", sa.Boolean),
    ("is_default", sa.Boolean),
    ("created_at", _tstz),
)
PLAYLISTS = _t(
    "catalog_playlists",
    ("id", sa.Integer),
    ("name", sa.String),
    ("source_url", sa.String),
    ("is_system", sa.Boolean),
    ("created_at", _tstz),
    ("updated_at", _tstz),
)
CHANNELS = _t(
    "catalog_channels",
    ("id", sa.Integer),
    ("playlist_id", sa.Integer),
    ("source_key", sa.String),
    ("name", sa.String),
    ("stream_url", sa.String),
    ("logo_url", sa.String),
    ("group_name", sa.String),
    ("kind", sa.String),
    ("rating", sa.String),
    ("delivery", sa.String),
    ("is_active", sa.Boolean),
    ("created_at", _tstz),
    ("updated_at", _tstz),
)
LIVE = _t(
    "live_channels",
    ("id", sa.Integer),
    ("name", sa.String),
    ("description", sa.String),
    ("logo_url", sa.String),
    ("source_type", sa.String),
    ("upstream_url", sa.String),
    ("delivery", sa.String),
    ("playback_id", sa.String),
    ("rating", sa.String),
    ("sort_order", sa.Integer),
    ("is_live", sa.Boolean),
    ("is_active", sa.Boolean),
    ("created_at", _tstz),
    ("updated_at", _tstz),
)
EPG = _t(
    "live_epg",
    ("channel_id", sa.Integer),
    ("title", sa.String),
    ("description", sa.String),
    ("starts_at", _tstz),
    ("ends_at", _tstz),
)
DEVICES = _t(
    "devices",
    ("user_id", sa.Integer),
    ("device_key", sa.String),
    ("name", sa.String),
    ("device_type", sa.String),
    ("browser", sa.String),
    ("os", sa.String),
    ("is_trusted", sa.Boolean),
    ("is_active", sa.Boolean),
    ("login_count", sa.Integer),
    ("last_ip", sa.String),
    ("last_seen_at", _tstz),
    ("created_at", _tstz),
)
SUBS = _t(
    "billing_subscriptions",
    ("user_id", sa.Integer),
    ("plan", sa.String),
    ("status", sa.String),
    ("cycle", sa.String),
    ("current_period_start", _tstz),
    ("current_period_end", _tstz),
    ("trial_ends_at", _tstz),
    ("trial_used", sa.Boolean),
    ("grace_ends_at", _tstz),
    ("cancel_at_period_end", sa.Boolean),
    ("cancelled_at", _tstz),
    ("provider", sa.String),
    ("external_subscription_id", sa.String),
    ("created_at", _tstz),
    ("updated_at", _tstz),
)
FAVORITES = _t(
    "library_favorites",
    ("user_id", sa.Integer),
    ("profile_id", sa.Integer),
    ("content_ref", sa.String),
    ("created_at", _tstz),
)
PROGRESS = _t(
    "library_progress",
    ("user_id", sa.Integer),
    ("profile_id", sa.Integer),
    ("content_ref", sa.String),
    ("position_s", sa.Integer),
    ("duration_s", sa.Integer),
    ("ratio", sa.Float),
    ("completed", sa.Boolean),
    ("created_at", _tstz),
    ("updated_at", _tstz),
)
HISTORY = _t(
    "library_history",
    ("user_id", sa.Integer),
    ("profile_id", sa.Integer),
    ("content_ref", sa.String),
    ("session_token", sa.String),
    ("watched_seconds", sa.Integer),
    ("watched_at", _tstz),
)
SESSIONS = _t(
    "playback_sessions",
    ("token", sa.String),
    ("user_id", sa.Integer),
    ("profile_id", sa.Integer),
    ("content_ref", sa.String),
    ("device_key", sa.String),
    ("ip", sa.String),
    ("user_agent", sa.String),
    ("started_at", _tstz),
    ("last_heartbeat_at", _tstz),
    ("ended_at", _tstz),
    ("end_reason", sa.String),
)
EVENTS = _t(
    "playback_events",
    ("user_id", sa.Integer),
    ("profile_id", sa.Integer),
    ("content_ref", sa.String),
    ("event_type", sa.String),
    ("position_s", sa.Integer),
    ("session_token", sa.String),
    ("created_at", _tstz),
)
QOE = _t(
    "playback_qoe",
    ("user_id", sa.Integer),
    ("content_ref", sa.String),
    ("session_token", sa.String),
    ("startup_time_ms", sa.Integer),
    ("rebuffer_count", sa.Integer),
    ("rebuffer_duration_ms", sa.Integer),
    ("watch_duration_s", sa.Integer),
    ("resolution", sa.String),
    ("device_type", sa.String),
    ("connection_type", sa.String),
    ("created_at", _tstz),
)
DRM_POLICIES = _t(
    "drm_policies",
    ("name", sa.String),
    ("max_resolution", sa.String),
    ("license_duration_s", sa.Integer),
    ("allow_offline", sa.Boolean),
    ("offline_validity_h", sa.Integer),
    ("allowed_device_classes", sa.String),
    ("require_hdcp", sa.Boolean),
    ("allow_screen_capture", sa.Boolean),
    ("is_default", sa.Boolean),
    ("created_at", _tstz),
    ("updated_at", _tstz),
)
RECO_BUCKETS = _t(
    "reco_play_buckets",
    ("content_ref", sa.String),
    ("bucket", _tstz),
    ("plays", sa.Integer),
)
RECO_AFFINITY = _t(
    "reco_profile_affinity",
    ("profile_id", sa.Integer),
    ("content_ref", sa.String),
    ("plays", sa.Integer),
    ("last_played_at", _tstz),
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _utc(value: Any, default: datetime | None = None) -> datetime | None:
    if value is None:
        return default
    if isinstance(value, str):  # defensive: raw SQLite text
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _clip(value: Any, length: int) -> str | None:
    return None if value is None else str(value)[:length]


def _stream(bind: sa.Connection, stmt: sa.Select[Any]) -> Iterator[Any]:
    # Per-statement options: Connection.execution_options() would mutate the
    # shared connection and turn every later INSERT into a server-side cursor.
    result = bind.execute(stmt.execution_options(stream_results=True, yield_per=BATCH))
    yield from result.mappings()


def _insert(
    bind: sa.Connection, table: sa.TableClause, rows: Iterable[dict[str, Any]]
) -> int:
    total, batch = 0, []
    for row in rows:
        batch.append(row)
        if len(batch) >= BATCH:
            bind.execute(sa.insert(table), batch)
            total += len(batch)
            batch = []
    if batch:
        bind.execute(sa.insert(table), batch)
        total += len(batch)
    return total


def _report(name: str, copied: int, skipped: Counter[str] | None = None) -> None:
    detail = f" skipped={dict(skipped)}" if skipped else ""
    log.info("v2-data %s copied=%d%s", name, copied, detail)


class Refs:
    """Legacy id → v2 content ref / default profile."""

    def __init__(self, profiles: dict[int, int], channels: dict[int, int]) -> None:
        self.profiles = profiles
        self.channels = channels

    def catalog(self, legacy_channel_id: int | None) -> str | None:
        new_id = (
            self.channels.get(legacy_channel_id)
            if legacy_channel_id is not None
            else None
        )
        return None if new_id is None else f"catalog:{new_id}"


# ── Steps ──────────────────────────────────────────────────────────────────


def _users(bind: sa.Connection) -> set[int]:
    def rows() -> Iterator[dict[str, Any]]:
        for u in _stream(bind, sa.select(L_USER).order_by(L_USER.c.id)):
            yield {
                "id": u["id"],
                "username": u["username"],
                "email": None,
                "password_hash": u["password_hash"] or UNUSABLE_PASSWORD,
                "role": "admin" if (u["role"] or "").lower() == "admin" else "user",
                "is_active": True if u["is_active"] is None else bool(u["is_active"]),
                "token_version": 1,
                "created_at": _utc(u["created_at"], NOW),
                "last_login_at": _utc(u["last_login"]),
                "last_login_ip": _clip(u["last_ip"], 45),
            }

    _report("users", _insert(bind, USERS, rows()))
    return set(bind.execute(sa.select(USERS.c.id)).scalars())


def _profiles(bind: sa.Connection, user_ids: set[int]) -> dict[int, int]:
    _insert(
        bind,
        PROFILES,
        (
            {
                "user_id": uid,
                "name": DEFAULT_PROFILE_NAME,
                "avatar": "default",
                "is_kids": False,
                "is_default": True,
                "created_at": NOW,
            }
            for uid in sorted(user_ids)
        ),
    )
    mapping = dict(
        bind.execute(
            sa.select(PROFILES.c.user_id, PROFILES.c.id).where(PROFILES.c.is_default)
        ).all()
    )
    _report("profiles(default)", len(mapping))
    return mapping


def _kind(url: str, group: str | None) -> str:
    path = url.lower().split("?", 1)[0]
    if path.endswith(VOD_EXTENSIONS) or any(
        k in (group or "").lower() for k in VOD_GROUP_HINTS
    ):
        return "vod"
    return "live"


def _rating(name: str, group: str | None) -> str:
    haystack = f"{group or ''} {name}".lower()
    if any(k in haystack for k in ADULT_HINTS):
        return "adult"
    if any(k in haystack for k in KIDS_HINTS):
        return "general"
    return "unrated"


def _catalog(bind: sa.Connection) -> dict[int, int]:
    playlist_ids: set[int] = set()

    def playlists() -> Iterator[dict[str, Any]]:
        for p in _stream(bind, sa.select(L_PLAYLIST).order_by(L_PLAYLIST.c.id)):
            playlist_ids.add(p["id"])
            yield {
                "id": p["id"],
                "name": _clip(p["name"], 128),
                "source_url": _clip(p["url"], 1024) or None,
                "is_system": False,
                "created_at": _utc(p["created_at"], NOW),
                "updated_at": _utc(p["updated_at"]) or _utc(p["created_at"], NOW),
            }

    _report("catalog.playlists", _insert(bind, PLAYLISTS, playlists()))
    next_id = (max(playlist_ids) + 1) if playlist_ids else 1
    bind.execute(
        sa.insert(PLAYLISTS).values(
            id=next_id,
            name=MANUAL_PLAYLIST,
            source_url=None,
            is_system=True,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    manual_id = next_id

    channel_map: dict[int, int] = {}
    seen: dict[tuple[int, str], int] = {}
    skipped: Counter[str] = Counter()

    def channels() -> Iterator[dict[str, Any]]:
        for c in _stream(bind, sa.select(L_CHANNEL).order_by(L_CHANNEL.c.id)):
            url = (c["url"] or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                skipped["non_http_url"] += 1
                continue
            playlist_id = (
                c["playlist_id"] if c["playlist_id"] in playlist_ids else manual_id
            )
            source_key = (
                "url:" + hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()
            )
            key = (playlist_id, source_key)
            if (
                key in seen
            ):  # duplicate URL inside one playlist → merge onto the first row
                channel_map[c["id"]] = seen[key]
                skipped["duplicate_merged"] += 1
                continue
            seen[key] = c["id"]
            channel_map[c["id"]] = c["id"]
            name = (c["name"] or "Untitled")[:256]
            yield {
                "id": c["id"],
                "playlist_id": playlist_id,
                "source_key": source_key,
                "name": name,
                "stream_url": url[:1024],
                "logo_url": _clip(c["logo"], 1024),
                "group_name": (c["group"] or "Uncategorized")[:128],
                "kind": _kind(url, c["group"]),
                "rating": _rating(name, c["group"]),
                "delivery": "proxy",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }

    _report("catalog.channels", _insert(bind, CHANNELS, channels()), skipped)
    return channel_map


def _live(bind: sa.Connection) -> None:
    live_ids: set[int] = set()
    ingest_without_key = 0

    def channels() -> Iterator[dict[str, Any]]:
        nonlocal ingest_without_key
        for c in _stream(bind, sa.select(L_LIVE).order_by(L_LIVE.c.id)):
            live_ids.add(c["id"])
            upstream = (c["hls_url"] or "").strip()
            external = upstream.lower().startswith(("http://", "https://"))
            if not external:
                ingest_without_key += 1
            yield {
                "id": c["id"],
                "name": (c["name"] or "Live")[:100],
                "description": _clip(c["description"], 500),
                "logo_url": _clip(c["logo"], 1024),
                "source_type": "external" if external else "ingest",
                "upstream_url": upstream[:1024] if external else None,
                "delivery": "proxy",
                "playback_id": secrets.token_hex(12),
                "rating": "unrated",
                "sort_order": c["id"],
                "is_live": False,
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }

    _report("live.channels", _insert(bind, LIVE, channels()))
    if ingest_without_key:
        log.warning(
            "v2-data live: %d ingest channel(s) need a new ingest key (admin → rotate key)",
            ingest_without_key,
        )

    seen: set[tuple[int, datetime]] = set()
    skipped: Counter[str] = Counter()

    def programmes() -> Iterator[dict[str, Any]]:
        for p in _stream(bind, sa.select(L_EPG).order_by(L_EPG.c.start_time)):
            starts, ends = _utc(p["start_time"]), _utc(p["end_time"])
            if p["live_channel_id"] not in live_ids:
                skipped["orphan"] += 1
                continue
            if starts is None or ends is None or ends <= starts:
                skipped["bad_time_range"] += 1
                continue
            if (p["live_channel_id"], starts) in seen:
                skipped["duplicate_start"] += 1
                continue
            seen.add((p["live_channel_id"], starts))
            yield {
                "channel_id": p["live_channel_id"],
                "title": (p["program_name"] or "—")[:200],
                "description": _clip(p["description"], 1000),
                "starts_at": starts,
                "ends_at": ends,
            }

    _report("live.epg", _insert(bind, EPG, programmes()), skipped)


def _devices(bind: sa.Connection, user_ids: set[int]) -> None:
    seen: set[tuple[int, str]] = set()
    skipped: Counter[str] = Counter()

    def rows() -> Iterator[dict[str, Any]]:
        for d in _stream(bind, sa.select(L_DEVICE)):
            if d["user_id"] not in user_ids:
                skipped["orphan"] += 1
                continue
            key = (
                "legacy-"
                + hashlib.sha1(
                    str(d["device_id"]).encode(), usedforsecurity=False
                ).hexdigest()[:33]
            )
            if (d["user_id"], key) in seen:
                skipped["duplicate"] += 1
                continue
            seen.add((d["user_id"], key))
            last_seen = _utc(d["last_seen"]) or _utc(d["created_at"], NOW)
            yield {
                "user_id": d["user_id"],
                "device_key": key,
                "name": (d["device_name"] or "Legacy device")[:100],
                "device_type": (d["device_type"] or "unknown")[:20],
                "browser": _clip(d["browser"], 50),
                "os": _clip(d["os"], 50),
                "is_trusted": False,
                "is_active": False,
                "login_count": max(1, d["login_count"] or 1),
                "last_ip": _clip(d["last_ip"], 45),
                "last_seen_at": last_seen,
                "created_at": _utc(d["created_at"]) or last_seen,
            }

    _report("devices(history, inactive)", _insert(bind, DEVICES, rows()), skipped)


def _plan(raw: Any) -> str:
    plan = (raw or "free").strip().lower()
    plan = PLAN_ALIASES.get(plan, plan)
    return plan if plan in PLANS else "free"


def _billing(bind: sa.Connection, user_ids: set[int]) -> None:
    covered: set[int] = set()
    skipped: Counter[str] = Counter()

    def rows() -> Iterator[dict[str, Any]]:
        for s in _stream(bind, sa.select(L_SUB)):
            uid = s["user_id"]
            if uid not in user_ids or uid in covered:
                skipped["orphan_or_duplicate"] += 1
                continue
            covered.add(uid)
            plan = _plan(s["plan"])
            status = (s["status"] or "active").lower()
            status = status if status in STATUSES else "active"
            if plan == "free":
                status = "active"
            elif status == "active" and s["auto_renew"] is False:
                status = (
                    "cancelled"  # v2 models "won't renew" as CANCELLED-until-period-end
                )
            yield {
                "user_id": uid,
                "plan": plan,
                "status": status,
                "cycle": "forever"
                if plan == "free"
                else (s["billing_cycle"] or "monthly")[:20],
                "current_period_start": _utc(s["started_at"]),
                "current_period_end": None if plan == "free" else _utc(s["expires_at"]),
                "trial_ends_at": _utc(s["trial_ends_at"]),
                "trial_used": s["trial_ends_at"] is not None,
                "grace_ends_at": _utc(s["grace_ends_at"]),
                "cancel_at_period_end": status == "cancelled",
                "cancelled_at": _utc(s["cancelled_at"]),
                "provider": _clip(s["payment_provider"], 30),
                "external_subscription_id": _clip(s["external_subscription_id"], 128),
                "created_at": _utc(s["created_at"], NOW),
                "updated_at": _utc(s["updated_at"], NOW),
            }

    copied = _insert(bind, SUBS, rows())

    def from_user_columns() -> Iterator[dict[str, Any]]:
        # Accounts whose plan only lived on the user row (admin-granted plans).
        for u in _stream(
            bind,
            sa.select(
                L_USER.c.id,
                L_USER.c.subscription_plan,
                L_USER.c.expire_date,
                L_USER.c.created_at,
            ),
        ):
            if u["id"] in covered:
                continue
            plan = _plan(u["subscription_plan"])
            yield {
                "user_id": u["id"],
                "plan": plan,
                "status": "active",
                "cycle": "forever" if plan == "free" else "monthly",
                "current_period_start": _utc(u["created_at"], NOW),
                "current_period_end": None
                if plan == "free"
                else _utc(u["expire_date"]),
                "trial_ends_at": None,
                "trial_used": False,
                "grace_ends_at": None,
                "cancel_at_period_end": False,
                "cancelled_at": None,
                "provider": None,
                "external_subscription_id": None,
                "created_at": NOW,
                "updated_at": NOW,
            }

    seeded = _insert(bind, SUBS, from_user_columns())
    _report("billing.subscriptions", copied + seeded, skipped)


def _library(bind: sa.Connection, refs: Refs) -> None:
    for name, source, target, build in (
        ("library.favorites", L_FAVORITE, FAVORITES, _favorite_row),
        ("library.progress", L_PROGRESS, PROGRESS, _progress_row),
        ("library.history", L_HISTORY, HISTORY, _history_row),
    ):
        skipped: Counter[str] = Counter()
        seen: set[tuple[int, str]] = set()
        unique = target is not HISTORY

        def rows(
            source: sa.TableClause = source,
            build: Callable[..., dict[str, Any]] = build,
            skipped: Counter[str] = skipped,
            seen: set[tuple[int, str]] = seen,
            unique: bool = unique,
        ) -> Iterator[dict[str, Any]]:
            for r in _stream(bind, sa.select(source)):
                profile_id = refs.profiles.get(r["user_id"])
                content_ref = refs.catalog(r["channel_id"])
                if profile_id is None or content_ref is None:
                    skipped["orphan"] += 1
                    continue
                if unique:
                    if (profile_id, content_ref) in seen:
                        skipped["duplicate"] += 1
                        continue
                    seen.add((profile_id, content_ref))
                yield build(r, r["user_id"], profile_id, content_ref)

        _report(name, _insert(bind, target, rows()), skipped)


def _favorite_row(r: Any, user_id: int, profile_id: int, ref: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "profile_id": profile_id,
        "content_ref": ref,
        "created_at": _utc(r["created_at"], NOW),
    }


def _progress_row(r: Any, user_id: int, profile_id: int, ref: str) -> dict[str, Any]:
    duration = max(0, r["total_duration"] or 0)
    position = max(0, r["last_position"] or 0)
    if duration:
        position = min(position, duration)
    ratio = (position / duration) if duration else 0.0
    updated = _utc(r["updated_at"]) or _utc(r["created_at"], NOW)
    return {
        "user_id": user_id,
        "profile_id": profile_id,
        "content_ref": ref,
        "position_s": position,
        "duration_s": duration,
        "ratio": min(max(ratio, 0.0), 1.0),
        "completed": bool(r["is_completed"]) or ratio >= 0.9,
        "created_at": _utc(r["created_at"]) or updated,
        "updated_at": updated,
    }


def _history_row(r: Any, user_id: int, profile_id: int, ref: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "profile_id": profile_id,
        "content_ref": ref,
        "session_token": None,
        "watched_seconds": max(0, r["duration"] or 0),
        "watched_at": _utc(r["timestamp"], NOW),
    }


def _playback(bind: sa.Connection, refs: Refs) -> None:
    skipped: Counter[str] = Counter()
    seen_tokens: set[str] = set()

    def sessions() -> Iterator[dict[str, Any]]:
        for s in _stream(bind, sa.select(L_SESSION)):
            profile_id = refs.profiles.get(s["user_id"])
            content_ref = refs.catalog(s["channel_id"])
            token = (s["token"] or "")[:64]
            if profile_id is None or content_ref is None or not token:
                skipped["orphan"] += 1
                continue
            if token in seen_tokens:
                skipped["duplicate"] += 1
                continue
            seen_tokens.add(token)
            started = _utc(s["started_at"], NOW)
            last = _utc(s["last_heartbeat"]) or started
            yield {
                "token": token,
                "user_id": s["user_id"],
                "profile_id": profile_id,
                "content_ref": content_ref,
                "device_key": "legacy",
                "ip": _clip(s["ip_address"], 45),
                "user_agent": _clip(s["user_agent"], 255),
                "started_at": started,
                "last_heartbeat_at": last,
                "ended_at": max(
                    started,
                    min(t for t in (_utc(s["expires_at"]), last, NOW) if t is not None),
                ),
                "end_reason": "migrated",
            }

    _report("playback.sessions(closed)", _insert(bind, SESSIONS, sessions()), skipped)

    skipped_events: Counter[str] = Counter()

    def events() -> Iterator[dict[str, Any]]:
        for e in _stream(bind, sa.select(L_EVENT)):
            profile_id = refs.profiles.get(e["user_id"])
            content_ref = refs.catalog(e["channel_id"])
            if profile_id is None or content_ref is None:
                skipped_events["orphan"] += 1
                continue
            yield {
                "user_id": e["user_id"],
                "profile_id": profile_id,
                "content_ref": content_ref,
                "event_type": (e["event_type"] or "unknown")[:16],
                "position_s": max(0, e["position"] or 0),
                "session_token": _clip(e["session_token"], 64),
                "created_at": _utc(e["created_at"], NOW),
            }

    _report("playback.events", _insert(bind, EVENTS, events()), skipped_events)

    skipped_qoe: Counter[str] = Counter()

    def qoe() -> Iterator[dict[str, Any]]:
        for m in _stream(bind, sa.select(L_METRICS)):
            content_ref = refs.catalog(m["channel_id"])
            if m["user_id"] not in refs.profiles or content_ref is None:
                skipped_qoe["orphan"] += 1
                continue
            yield {
                "user_id": m["user_id"],
                "content_ref": content_ref,
                "session_token": _clip(m["session_token"], 64),
                "startup_time_ms": m["startup_time_ms"],
                "rebuffer_count": max(0, m["rebuffer_count"] or 0),
                "rebuffer_duration_ms": max(0, m["rebuffer_duration_ms"] or 0),
                "watch_duration_s": max(0, m["watch_duration_seconds"] or 0),
                "resolution": _clip(m["resolution"], 20),
                "device_type": _clip(m["device_type"], 20),
                "connection_type": _clip(m["connection_type"], 20),
                "created_at": _utc(m["created_at"], NOW),
            }

    _report("playback.qoe", _insert(bind, QOE, qoe()), skipped_qoe)


def _recommendations(bind: sa.Connection, refs: Refs) -> None:
    """Seed the read model from legacy 'play' events so Trending is not empty on day one."""
    buckets: Counter[tuple[str, datetime]] = Counter()
    affinity: dict[tuple[int, str], list[Any]] = defaultdict(lambda: [0, None])
    for e in _stream(bind, sa.select(L_EVENT).where(L_EVENT.c.event_type == "play")):
        content_ref = refs.catalog(e["channel_id"])
        profile_id = refs.profiles.get(e["user_id"])
        at = _utc(e["created_at"])
        if content_ref is None or profile_id is None or at is None:
            continue
        buckets[(content_ref, at.replace(minute=0, second=0, microsecond=0))] += 1
        entry = affinity[(profile_id, content_ref)]
        entry[0] += 1
        entry[1] = at if entry[1] is None or at > entry[1] else entry[1]
    _insert(
        bind,
        RECO_BUCKETS,
        ({"content_ref": r, "bucket": b, "plays": n} for (r, b), n in buckets.items()),
    )
    _insert(
        bind,
        RECO_AFFINITY,
        (
            {"profile_id": p, "content_ref": r, "plays": n, "last_played_at": at}
            for (p, r), (n, at) in affinity.items()
        ),
    )
    _report("recommendations(seeded buckets/affinity)", len(buckets) + len(affinity))


def _drm(bind: sa.Connection) -> None:
    def policies() -> Iterator[dict[str, Any]]:
        for p in _stream(bind, sa.select(L_DRM_POLICY)):
            classes = sorted(
                {c.strip() for c in (p["allowed_device_types"] or "").split(",")}
                & DEVICE_CLASSES
            )
            resolution = (
                p["max_resolution"] if p["max_resolution"] in RESOLUTIONS else "2160p"
            )
            yield {
                "name": (p["name"] or "policy")[:50],
                "max_resolution": resolution,
                "license_duration_s": min(
                    max(p["license_duration_seconds"] or 600, 60), 86_400
                ),
                "allow_offline": bool(p["allow_offline"]),
                "offline_validity_h": min(
                    max(p["offline_validity_hours"] or 48, 1), 720
                ),
                "allowed_device_classes": ",".join(classes) or None,
                "require_hdcp": bool(p["require_hdcp"]),
                "allow_screen_capture": bool(p["allow_screen_capture"]),
                "is_default": False,
                "created_at": _utc(p["created_at"], NOW),
                "updated_at": NOW,
            }

    _report("drm.policies", _insert(bind, DRM_POLICIES, policies()))
    legacy_protected = bind.execute(
        sa.select(sa.func.count()).select_from(L_DRM_CONTENT)
    ).scalar_one()
    if legacy_protected:
        log.warning(
            "v2-data drm: %d legacy protected item(s) NOT migrated — their keys were exposed in clear (SEC-07). "
            "Re-protect them (admin → DRM) to issue fresh envelope-encrypted keys.",
            legacy_protected,
        )


def _align_sequences(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    for table in (
        "identity_users",
        "catalog_playlists",
        "catalog_channels",
        "live_channels",
    ):
        bind.execute(
            sa.text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), (SELECT MAX(id) IS NOT NULL FROM {table}))"
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    user_ids = _users(bind)
    profiles = _profiles(bind, user_ids)
    channel_map = _catalog(bind)
    refs = Refs(profiles, channel_map)
    _live(bind)
    _devices(bind, user_ids)
    _billing(bind, user_ids)
    _library(bind, refs)
    _playback(bind, refs)
    _recommendations(bind, refs)
    _drm(bind)
    _align_sequences(bind)


def downgrade() -> None:
    """Empties the v2 tables (legacy tables are untouched until b2c0de000003)."""
    bind = op.get_bind()
    for table in (
        "reco_profile_affinity",
        "reco_play_buckets",
        "drm_policies",
        "playback_qoe",
        "playback_events",
        "playback_sessions",
        "library_history",
        "library_progress",
        "library_favorites",
        "billing_subscriptions",
        "devices",
        "live_epg",
        "live_channels",
        "catalog_channels",
        "catalog_playlists",
        "profiles",
        "identity_users",
    ):
        bind.execute(sa.text(f"DELETE FROM {table}"))
