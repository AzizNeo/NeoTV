"""Integration events — the asynchronous contract between modules.

Rules:
* ``NAME`` is the stable wire name ``<owner-module>.<past-tense-fact>``.
* Changing a field ⇒ bump ``VERSION`` and register an upcaster in the
  owning module (see ``app.kernel.events.registry.EventRegistry.upcaster``).
* Only primitives (str/int/bool/None) — payloads are JSON on the wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class UserRegistered:
    NAME: ClassVar[str] = "identity.user_registered"
    VERSION: ClassVar[int] = 1
    user_id: int
    username: str
    email: str | None
    registered_at: str


@dataclass(frozen=True, slots=True)
class UserLoggedIn:
    NAME: ClassVar[str] = "identity.user_logged_in"
    VERSION: ClassVar[int] = 1
    user_id: int
    client_device_id: str | None
    user_agent: str
    ip: str
    occurred_at: str


@dataclass(frozen=True, slots=True)
class UserStatusChanged:
    NAME: ClassVar[str] = "identity.user_status_changed"
    VERSION: ClassVar[int] = 1
    user_id: int
    is_active: bool
    occurred_at: str


@dataclass(frozen=True, slots=True)
class DeviceRevoked:
    NAME: ClassVar[str] = "devices.device_revoked"
    VERSION: ClassVar[int] = 1
    user_id: int
    device_key: str
    occurred_at: str


@dataclass(frozen=True, slots=True)
class ProfileDeleted:
    NAME: ClassVar[str] = "profile.profile_deleted"
    VERSION: ClassVar[int] = 1
    user_id: int
    profile_id: int
    occurred_at: str


@dataclass(frozen=True, slots=True)
class SubscriptionChanged:
    NAME: ClassVar[str] = "billing.subscription_changed"
    VERSION: ClassVar[int] = 1
    user_id: int
    plan: str
    status: str
    max_streams: int
    effective_at: str


@dataclass(frozen=True, slots=True)
class ContentRemoved:
    NAME: ClassVar[str] = "content.removed"
    VERSION: ClassVar[int] = 1
    content_ref: str
    occurred_at: str


@dataclass(frozen=True, slots=True)
class PlaybackSessionStarted:
    NAME: ClassVar[str] = "playback.session_started"
    VERSION: ClassVar[int] = 1
    session_token: str
    user_id: int
    profile_id: int
    content_ref: str
    started_at: str


@dataclass(frozen=True, slots=True)
class PlaybackSessionEnded:
    NAME: ClassVar[str] = "playback.session_ended"
    VERSION: ClassVar[int] = 1
    session_token: str
    user_id: int
    profile_id: int
    content_ref: str
    ended_at: str
    watched_seconds: int


@dataclass(frozen=True, slots=True)
class EmailQueued:
    """notifications → notifications: deliver one queued mail (async, retried by the outbox)."""

    NAME: ClassVar[str] = "notifications.email_queued"
    VERSION: ClassVar[int] = 1
    message_id: str
    template: str


ALL_EVENTS: tuple[type, ...] = (
    UserRegistered,
    UserLoggedIn,
    UserStatusChanged,
    DeviceRevoked,
    ProfileDeleted,
    SubscriptionChanged,
    ContentRemoved,
    PlaybackSessionStarted,
    PlaybackSessionEnded,
    EmailQueued,
)
