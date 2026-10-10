"""PUBLIC surface of the playback module — the plug sockets of the player.

Extension points owned by playback (declared in its manifest):

* ``playback.content_providers`` — one per content namespace (``catalog``,
  ``live`` ...): describes content, renders cards, resolves a playable source.
* ``playback.policies`` — authorisation rules evaluated before a session opens
  (kids rating, entitlements, geo ...). Ordered by ``order``.
* ``playback.source_enhancers`` — post-processing of a resolved source (DRM
  key delivery, ad markers ...).

Adding a content type, a rule or a DRM scheme = a new class in the owning
module + one ``ExtensionSpec`` line in that module's manifest. Playback is
never edited.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.shared_kernel.content import ContentRef


class ContentKind(StrEnum):
    LIVE = "live"
    VOD = "vod"


class Rating(StrEnum):
    GENERAL = "general"
    TEEN = "teen"
    ADULT = "adult"
    UNRATED = "unrated"


@dataclass(frozen=True, slots=True)
class ContentCard:
    ref: str
    title: str
    image: str | None
    group: str | None
    kind: ContentKind
    rating: Rating


@dataclass(frozen=True, slots=True)
class ContentDescriptor:
    ref: ContentRef
    title: str
    kind: ContentKind
    rating: Rating
    group: str | None = None
    tier: str = "standard"


@dataclass(frozen=True, slots=True)
class PlaybackContext:
    user_id: int
    profile_id: int
    is_kids: bool
    device_key: str
    ip: str
    user_agent: str
    content: ContentRef
    session_token: str = ""
    grant_expires_at: int = 0


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    manifest_url: str
    is_live: bool
    mime_type: str = "application/vnd.apple.mpegurl"
    drm: dict[str, str] | None = None
    extras: dict[str, str] = field(default_factory=dict)

    def with_drm(self, drm: dict[str, str]) -> ResolvedSource:
        return replace(self, drm=drm)


@dataclass(frozen=True, slots=True)
class Deny:
    code: str
    message: str


class ContentProvider(Protocol):
    namespace: str

    def describe(self, content_id: int) -> ContentDescriptor | None: ...
    def cards(self, content_ids: list[int]) -> list[ContentCard]: ...
    def resolve(self, ctx: PlaybackContext, descriptor: ContentDescriptor) -> ResolvedSource: ...


class PlaybackPolicy(Protocol):
    name: str
    order: int

    def evaluate(self, ctx: PlaybackContext, descriptor: ContentDescriptor) -> Deny | None: ...


class SourceEnhancer(Protocol):
    name: str

    def enhance(
        self, ctx: PlaybackContext, descriptor: ContentDescriptor, source: ResolvedSource
    ) -> ResolvedSource: ...


INTERNAL_URI_PREFIX = "/api/v1/"
"""Playlist attribute URIs (EXT-X-KEY, EXT-X-SESSION-KEY, EXT-X-MAP) that are
root-relative paths under this prefix address *this* API (e.g. DRM key
delivery written by our packager). The HLS proxy re-signs them as internal
grants instead of proxying them upstream. Endpoints receiving such grants
must still check that the asset belongs to the session's content."""


class StreamUrlFactory(Protocol):
    """Capability ``playback.urls``: builds signed media URLs bound to a playback session."""

    def proxied(self, upstream_url: str, ctx: PlaybackContext) -> str: ...
    def signed(self, internal_path: str, ctx: PlaybackContext) -> str: ...
    def signed_entry(self, prefix: str, entry: str, ctx: PlaybackContext) -> str: ...


@dataclass(frozen=True, slots=True)
class MediaGrant:
    user_id: int
    session_token: str
    target: str
    expires_at: int


class SessionInactiveError(Exception):
    """The playback session behind a media grant has ended."""


class GrantVerifier(Protocol):
    """Capability ``playback.grants``: validates signed media URLs (proxy, HLS assets, DRM keys)."""

    def verify(self, params: object, *, path: str | None = None, require_live_session: bool = False) -> MediaGrant: ...


class ContentDirectory(Protocol):
    """Capability ``playback.content``: namespace-agnostic content lookup."""

    def cards(self, refs: list[str]) -> dict[str, ContentCard]: ...
    def describe(self, ref: ContentRef) -> ContentDescriptor | None: ...


@dataclass(frozen=True, slots=True)
class ActiveSessionView:
    token: str
    user_id: int
    profile_id: int
    content_ref: str
    ip: str | None
    user_agent: str | None
    started_at: datetime
    last_heartbeat_at: datetime


class SessionDirectory(Protocol):
    """Capability ``playback.sessions``: live playback sessions (read + admin terminate)."""

    def is_active(self, session_token: str) -> bool: ...
    def owner_of(self, session_token: str) -> int | None: ...
    def describe(self, session_token: str) -> ActiveSessionView | None: ...
    def active_count(self) -> int: ...
    def list_active(self, limit: int = 200) -> list[ActiveSessionView]: ...
    def terminate(self, session_token: str) -> bool: ...


__all__ = [
    "INTERNAL_URI_PREFIX",
    "ActiveSessionView",
    "ContentCard",
    "ContentDescriptor",
    "ContentDirectory",
    "ContentKind",
    "ContentProvider",
    "Deny",
    "GrantVerifier",
    "MediaGrant",
    "PlaybackContext",
    "PlaybackPolicy",
    "Rating",
    "ResolvedSource",
    "SessionDirectory",
    "SessionInactiveError",
    "SourceEnhancer",
    "StreamUrlFactory",
]
