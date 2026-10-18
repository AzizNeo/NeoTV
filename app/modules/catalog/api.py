"""PUBLIC surface of the catalog module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

NAMESPACE = "catalog"


@dataclass(frozen=True, slots=True)
class CatalogStats:
    channels: int
    live: int
    vod: int
    playlists: int


@dataclass(frozen=True, slots=True)
class ChannelListing:
    """One active channel as other modules may list it (never its stream URL)."""

    ref: str
    id: int
    name: str
    logo: str | None
    group: str
    kind: str
    rating: str
    added_at: datetime


class CatalogReader(Protocol):
    """Capability ``catalog.read`` — read-only queries used by other modules."""

    def similar(self, channel_id: int, limit: int) -> list[int]: ...
    def by_groups(self, groups: list[str], *, exclude_ids: list[int], limit: int) -> list[int]: ...
    def groups_of(self, channel_ids: list[int]) -> dict[int, str]: ...
    def stats(self) -> CatalogStats: ...
    def listing(self, *, kind: Literal["live", "vod"], kids_only: bool) -> list[ChannelListing]:
        """Every active channel of a kind, ordered by group then name; kids profiles see kids ratings only."""
        ...


__all__ = ["NAMESPACE", "CatalogReader", "CatalogStats", "ChannelListing"]
