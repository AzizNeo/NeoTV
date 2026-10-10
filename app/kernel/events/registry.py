"""Event type registry with schema versioning and upcasting.

Events are frozen dataclasses (``app.shared_kernel.events``) that carry two
class attributes: ``NAME`` (stable wire name) and ``VERSION``. Payloads are
stored with their version; when a newer class version exists, registered
upcasters migrate the payload step by step (v1 → v2 → ...), so messages that
were already queued survive a deploy that changes the event shape.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

from app.kernel.events.bus import UnknownEventTypeError

Upcaster = Callable[[dict[str, Any]], dict[str, Any]]


class EventSchemaError(TypeError):
    pass


class MissingUpcasterError(LookupError):
    pass


class EventRegistry:
    def __init__(self) -> None:
        self._types: dict[str, type] = {}
        self._upcasters: dict[tuple[str, int], Upcaster] = {}

    def register(self, event_type: type) -> type:
        name = getattr(event_type, "NAME", None)
        version = getattr(event_type, "VERSION", None)
        if not isinstance(name, str) or not isinstance(version, int) or not dataclasses.is_dataclass(event_type):
            raise EventSchemaError(f"{event_type!r} must be a dataclass with str NAME and int VERSION")
        existing = self._types.get(name)
        if existing is not None and existing is not event_type:
            raise EventSchemaError(f"event name '{name}' already bound to {existing.__qualname__}")
        self._types[name] = event_type
        return event_type

    def upcaster(self, name: str, from_version: int) -> Callable[[Upcaster], Upcaster]:
        def decorator(fn: Upcaster) -> Upcaster:
            key = (name, from_version)
            if key in self._upcasters:
                raise EventSchemaError(f"upcaster for {name} v{from_version} already registered")
            self._upcasters[key] = fn
            return fn

        return decorator

    def type_for(self, name: str) -> type:
        try:
            return self._types[name]
        except KeyError:
            raise UnknownEventTypeError(name) from None

    def names(self) -> list[str]:
        return sorted(self._types)

    def encode(self, event: Any) -> tuple[str, int, str]:
        event_type = type(event)
        registered = self._types.get(getattr(event_type, "NAME", ""))
        if registered is not event_type:
            raise UnknownEventTypeError(f"{event_type.__qualname__} is not registered")
        payload = dataclasses.asdict(event)
        return event_type.NAME, event_type.VERSION, json.dumps(payload, separators=(",", ":"), default=str)

    def decode(self, name: str, version: int, raw: str) -> Any:
        event_type = self.type_for(name)
        data: dict[str, Any] = json.loads(raw)
        current = version
        while current < event_type.VERSION:  # type: ignore[attr-defined]
            upcaster = self._upcasters.get((name, current))
            if upcaster is None:
                raise MissingUpcasterError(f"no upcaster for {name} v{current} → v{current + 1}")
            data = upcaster(data)
            current += 1
        code_version: int = event_type.VERSION  # type: ignore[attr-defined]
        if current > code_version:
            raise EventSchemaError(f"{name} payload v{current} is newer than code v{code_version}")
        return event_type(**data)
