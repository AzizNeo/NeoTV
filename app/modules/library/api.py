"""PUBLIC surface of the library module."""

from __future__ import annotations

from typing import Protocol


class LibrarySignals(Protocol):
    """Capability ``library.signals``: taste signals for other modules
    (e.g. recommendations) without exposing the library tables."""

    def favorite_refs(self, profile_id: int, limit: int = 200) -> list[str]: ...
    def recent_refs(self, profile_id: int, limit: int = 50) -> list[str]: ...


__all__ = ["LibrarySignals"]
