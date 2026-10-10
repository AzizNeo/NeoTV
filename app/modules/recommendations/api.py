"""PUBLIC surface of the recommendations module."""

from __future__ import annotations

from typing import Protocol


class TrendingReader(Protocol):
    """Capability ``recommendations.trending``: globally popular content refs."""

    def trending_refs(self, *, hours: int, limit: int) -> list[str]: ...


__all__ = ["TrendingReader"]
