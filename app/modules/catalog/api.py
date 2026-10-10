"""PUBLIC surface of the catalog module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

NAMESPACE = "catalog"


@dataclass(frozen=True, slots=True)
class CatalogStats:
    channels: int
    live: int
    vod: int
    playlists: int


class CatalogReader(Protocol):
    """Capability ``catalog.read`` — read-only queries used by other modules."""

    def similar(self, channel_id: int, limit: int) -> list[int]: ...
    def by_groups(self, groups: list[str], *, exclude_ids: list[int], limit: int) -> list[int]: ...
    def groups_of(self, channel_ids: list[int]) -> dict[int, str]: ...
    def stats(self) -> CatalogStats: ...


__all__ = ["NAMESPACE", "CatalogReader", "CatalogStats"]
