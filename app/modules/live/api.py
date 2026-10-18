"""PUBLIC surface of the live module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

NAMESPACE = "live"


@dataclass(frozen=True, slots=True)
class LiveStats:
    channels: int
    on_air: int
    transcoding: int


@dataclass(frozen=True, slots=True)
class LiveListing:
    """One active live channel as other modules may list it (never its upstream or ingest details)."""

    ref: str
    id: int
    name: str
    logo: str | None
    rating: str
    epg_channel_id: str | None
    added_at: datetime


class LiveReader(Protocol):
    """Capability ``live.read``."""

    def stats(self) -> LiveStats: ...
    def listing(self, *, kids_only: bool) -> list[LiveListing]:
        """Active channels in the operator's order; kids profiles see kids ratings only."""
        ...


__all__ = ["NAMESPACE", "LiveListing", "LiveReader", "LiveStats"]
