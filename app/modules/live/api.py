"""PUBLIC surface of the live module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

NAMESPACE = "live"


@dataclass(frozen=True, slots=True)
class LiveStats:
    channels: int
    on_air: int
    transcoding: int


class LiveReader(Protocol):
    """Capability ``live.read``."""

    def stats(self) -> LiveStats: ...


__all__ = ["NAMESPACE", "LiveReader", "LiveStats"]
