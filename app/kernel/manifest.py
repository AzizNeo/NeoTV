"""The module contract.

A module is a puzzle piece. ``ModuleManifest`` is the shape of its edges:
what it provides, what it needs, which routes/tasks/listeners/permissions/
extension contributions it brings. The kernel reads *only* the manifest; it
never scans a module's files by convention.

Everything that references code does so through lazy dotted paths
(``"package.module:attribute"``) so that importing a manifest is cheap and any
import failure is attributed to the owning module by name.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

ServiceKey = type | str


@dataclass(frozen=True, slots=True)
class RouteSpec:
    blueprint: str  # "app.modules.billing.http.routes:blueprint"
    url_prefix: str  # "/api/v1/billing"


@dataclass(frozen=True, slots=True)
class SubscriptionSpec:
    event: str  # "identity.user_registered"
    consumer: str  # globally unique: "<module>.<handler>"
    handler: str  # "app.modules.billing.handlers:on_user_registered"
    queue: str = "outbox"


@dataclass(frozen=True, slots=True)
class ExtensionSpec:
    point: str  # "playback.policies"
    factory: str  # dotted path to callable(container) -> object


@dataclass(frozen=True)
class ModuleManifest:
    name: str
    version: str
    description: str = ""
    provides: Mapping[str, ServiceKey] = field(default_factory=dict)
    requires: frozenset[str] = frozenset()
    optional_requires: frozenset[str] = frozenset()
    models: tuple[str, ...] = ()  # modules defining ORM tables (imported at load → metadata is complete)
    services: Callable[[Any], None] | None = None
    routes: tuple[RouteSpec, ...] = ()
    subscriptions: tuple[SubscriptionSpec, ...] = ()
    task_modules: tuple[str, ...] = ()
    beat_schedule: Mapping[str, dict[str, Any]] = field(default_factory=dict)
    task_routes: Mapping[str, dict[str, str]] = field(default_factory=dict)
    error_map: Mapping[type[Exception], tuple[int, str]] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()
    extension_points: tuple[str, ...] = ()
    extensions: tuple[ExtensionSpec, ...] = ()
    cli: tuple[str, ...] = ()  # dotted paths to click groups/commands
    post_boot: str | None = None  # dotted path to callable(container, app) — validation hooks

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"invalid module name {self.name!r}")
        overlap = self.requires & self.optional_requires
        if overlap:
            raise ValueError(f"[{self.name}] capability both required and optional: {sorted(overlap)}")
        for cap in self.provides:
            if not cap.startswith(f"{self.name}."):
                raise ValueError(f"[{self.name}] provided capability '{cap}' must be namespaced '{self.name}.*'")
        for point in self.extension_points:
            if not point.startswith(f"{self.name}."):
                raise ValueError(f"[{self.name}] extension point '{point}' must be namespaced '{self.name}.*'")
        for perm in self.permissions:
            if ":" not in perm:
                raise ValueError(f"[{self.name}] permission '{perm}' must look like 'area:action'")
        consumers = [s.consumer for s in self.subscriptions]
        if len(consumers) != len(set(consumers)):
            raise ValueError(f"[{self.name}] duplicate consumer names in subscriptions")
        for spec in self.subscriptions:
            if not spec.consumer.startswith(f"{self.name}."):
                raise ValueError(f"[{self.name}] consumer '{spec.consumer}' must be namespaced '{self.name}.*'")
