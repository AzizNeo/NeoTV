"""Time is a dependency. Business rules ask a ``Clock``; tests freeze it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


def utcnow() -> datetime:
    """Timezone-aware UTC now. ``datetime.utcnow()`` is deprecated and naive — never use it."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetime given where an aware UTC datetime is required")
    return value.astimezone(UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utcnow()


class FrozenClock:
    """Deterministic clock for tests."""

    def __init__(self, at: datetime | None = None) -> None:
        self._now = ensure_utc(at) if at else utcnow()

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> datetime:
        self._now = self._now + timedelta(**delta)
        return self._now

    def set(self, at: datetime) -> None:
        self._now = ensure_utc(at)
