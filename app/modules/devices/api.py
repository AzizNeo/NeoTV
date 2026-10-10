"""PUBLIC surface of the devices module."""

from __future__ import annotations

from typing import Protocol


class DeviceStats(Protocol):
    def active_devices(self) -> int: ...


__all__ = ["DeviceStats"]
