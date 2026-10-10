"""Capability index: resolve *optional* collaborators by capability name.

A module that merely *can use* another module (``optional_requires``) must not
import that module's code — otherwise deleting the other module would break
it. Instead it asks the index by capability name and receives either the
service or ``None`` (graceful degradation). The consumer types the result
with a Protocol it defines itself (consumer-owned port).
"""

from __future__ import annotations

from typing import Any

from app.kernel.container import Container, ServiceNotRegisteredError
from app.kernel.manifest import ServiceKey


class UnknownCapabilityError(LookupError):
    pass


class CapabilityIndex:
    def __init__(self, container: Container) -> None:
        self._container = container
        self._keys: dict[str, ServiceKey] = {}

    def bind(self, capability: str, key: ServiceKey) -> None:
        self._keys[capability] = key

    def is_available(self, capability: str) -> bool:
        return capability in self._keys

    def optional(self, capability: str) -> Any | None:
        key = self._keys.get(capability)
        return None if key is None else self._container.resolve(key)

    def required(self, capability: str) -> Any:
        key = self._keys.get(capability)
        if key is None:
            raise UnknownCapabilityError(f"capability '{capability}' is not provided by any enabled module")
        try:
            return self._container.resolve(key)
        except ServiceNotRegisteredError as exc:  # pragma: no cover - guarded at boot
            raise UnknownCapabilityError(capability) from exc

    def names(self) -> list[str]:
        return sorted(self._keys)
