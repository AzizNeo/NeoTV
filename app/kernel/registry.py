"""Module registry: validates the puzzle, then assembles it.

Phase 1 — ``resolve_order()`` (pure, no side effects):
    duplicate names, typos in DISABLED_MODULES, duplicate capabilities,
    missing/disabled dependencies, kernel requirements, cycles → named errors;
    otherwise a deterministic topological boot order.

Phase 2 — ``boot()``:
    services → declared capabilities really registered → extension points →
    routes → event subscriptions → error mappings → permissions → extension
    contributions → CLI → post-boot hooks → global URL-collision check.
"""

from __future__ import annotations

import importlib
import logging
from collections import deque
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from flask import Flask

from app.kernel.errors import (
    CircularModuleDependencyError,
    DisabledDependencyError,
    DuplicateCapabilityError,
    DuplicateModuleError,
    DuplicateRouteError,
    HandlerImportError,
    MissingCapabilityError,
    ModuleContractError,
    UnknownModuleError,
)
from app.kernel.manifest import ModuleManifest

if TYPE_CHECKING:
    from app.kernel.container import Container
    from app.kernel.events.bus import EventBus
    from app.kernel.extensions import ExtensionRegistry
    from app.kernel.http.errors import ErrorMap
    from app.kernel.security.permissions import PermissionCatalog

_log = logging.getLogger("kernel.registry")

#: Capabilities the kernel itself cannot run without (a module must provide them).
KERNEL_REQUIREMENTS: frozenset[str] = frozenset({"identity.authentication"})


def import_attr(path: str, *, owner: str) -> Any:
    module_path, sep, attribute = path.partition(":")
    if not sep or not module_path or not attribute:
        raise ModuleContractError(owner, f"'{path}' is not in 'package.module:attribute' form")
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # every failure in the import chain is attributed to the owner
        raise HandlerImportError(owner, path, exc) from exc
    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise ModuleContractError(owner, f"'{path}': attribute '{attribute}' not found") from exc


def load_manifests(installed: Iterable[str]) -> list[ModuleManifest]:
    manifests: list[ModuleManifest] = []
    for package in installed:
        short = package.rsplit(".", 1)[-1]
        manifest = import_attr(f"{package}.manifest:manifest", owner=short)
        if not isinstance(manifest, ModuleManifest):
            raise ModuleContractError(short, "`manifest` is not a ModuleManifest instance")
        if manifest.name != short:
            raise ModuleContractError(short, f"manifest.name '{manifest.name}' must equal package name '{short}'")
        for models_module in manifest.models:
            try:
                importlib.import_module(models_module)
            except Exception as exc:
                raise HandlerImportError(short, models_module, exc) from exc
        manifests.append(manifest)
    return manifests


class ModuleRegistry:
    def __init__(
        self,
        manifests: Sequence[ModuleManifest],
        *,
        disabled: frozenset[str] = frozenset(),
        kernel_requirements: frozenset[str] = KERNEL_REQUIREMENTS,
    ) -> None:
        names = [m.name for m in manifests]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise DuplicateModuleError(f"modules installed twice: {duplicates}")
        unknown = sorted(disabled - set(names))
        if unknown:
            raise UnknownModuleError(f"DISABLED_MODULES contains unknown module(s): {unknown}")
        self._all = list(manifests)
        self._active = [m for m in manifests if m.name not in disabled]
        self._disabled = [m for m in manifests if m.name in disabled]
        self._kernel_requirements = kernel_requirements
        self._order: list[ModuleManifest] | None = None

    # ── Introspection ──────────────────────────────────────────────────────
    @property
    def active(self) -> list[ModuleManifest]:
        return list(self._order or self._active)

    @property
    def disabled(self) -> list[ModuleManifest]:
        return list(self._disabled)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "provides": sorted(m.provides),
                "requires": sorted(m.requires),
                "optional_requires": sorted(m.optional_requires),
                "enabled": m not in self._disabled,
            }
            for m in self._all
        ]

    # ── Phase 1 ────────────────────────────────────────────────────────────
    def resolve_order(self) -> list[ModuleManifest]:
        providers: dict[str, str] = {}
        for manifest in self._active:
            for capability in manifest.provides:
                if capability in providers:
                    raise DuplicateCapabilityError(capability, providers[capability], manifest.name)
                providers[capability] = manifest.name
        disabled_capabilities = {cap: m.name for m in self._disabled for cap in m.provides}

        for capability in sorted(self._kernel_requirements):
            if capability in providers:
                continue
            if capability in disabled_capabilities:
                raise DisabledDependencyError("kernel", capability, disabled_capabilities[capability])
            raise MissingCapabilityError("kernel", capability)

        dependencies: dict[str, set[str]] = {m.name: set() for m in self._active}
        for manifest in self._active:
            for capability in sorted(manifest.requires):
                if capability in providers:
                    dependencies[manifest.name].add(providers[capability])
                elif capability in disabled_capabilities:
                    raise DisabledDependencyError(manifest.name, capability, disabled_capabilities[capability])
                else:
                    raise MissingCapabilityError(manifest.name, capability)
            for capability in manifest.optional_requires:
                if capability in providers:
                    dependencies[manifest.name].add(providers[capability])
            dependencies[manifest.name].discard(manifest.name)

        by_name = {m.name: m for m in self._active}
        indegree = {name: len(deps) for name, deps in dependencies.items()}
        dependents: dict[str, set[str]] = {name: set() for name in dependencies}
        for name, deps in dependencies.items():
            for dep in deps:
                dependents[dep].add(name)

        queue = deque(sorted(name for name, degree in indegree.items() if degree == 0))
        order: list[ModuleManifest] = []
        while queue:
            name = queue.popleft()
            order.append(by_name[name])
            for dependent in sorted(dependents[name]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self._active):
            cyclic = sorted(name for name, degree in indegree.items() if degree > 0)
            raise CircularModuleDependencyError(f"circular module dependency between: {cyclic}")
        self._order = order
        return order

    # ── Phase 2 ────────────────────────────────────────────────────────────
    def boot(
        self,
        app: Flask,
        container: Container,
        *,
        bus: EventBus,
        error_map: ErrorMap,
        extensions: ExtensionRegistry,
        permissions: PermissionCatalog,
    ) -> list[ModuleManifest]:
        from app.kernel.capabilities import CapabilityIndex
        from app.kernel.events.bus import Subscription

        order = self._order or self.resolve_order()
        capabilities = container.resolve(CapabilityIndex)

        for manifest in self._disabled:
            for point in manifest.extension_points:
                extensions.mark_disabled(point)

        # 1) services + capability verification
        for manifest in order:
            if manifest.services is not None:
                with container.owned_by(manifest.name):
                    manifest.services(container)
            for capability, key in manifest.provides.items():
                if not container.has(key):
                    raise ModuleContractError(
                        manifest.name, f"declares capability '{capability}' but never registers '{key}'"
                    )
                capabilities.bind(capability, key)

        # 2) extension points must exist before anyone contributes
        for manifest in order:
            for point in manifest.extension_points:
                extensions.declare(point, manifest.name)

        # 3) routes, subscriptions, errors, permissions, extensions, cli
        for manifest in order:
            for spec in manifest.routes:
                blueprint = import_attr(spec.blueprint, owner=manifest.name)
                if blueprint.name in app.blueprints:
                    raise DuplicateRouteError(
                        f"[module:{manifest.name}] blueprint name '{blueprint.name}' is already registered"
                    )
                app.register_blueprint(blueprint, url_prefix=spec.url_prefix)
            for sub in manifest.subscriptions:
                handler = import_attr(sub.handler, owner=manifest.name)
                bus.subscribe(Subscription(sub.event, sub.consumer, handler, sub.queue, owner=manifest.name))
            for exception, (status, code) in manifest.error_map.items():
                error_map.register(exception, status=status, code=code, owner=manifest.name)
            for permission in manifest.permissions:
                permissions.declare(permission, manifest.name)
            for ext in manifest.extensions:
                factory = import_attr(ext.factory, owner=manifest.name)
                extensions.contribute(ext.point, manifest.name, factory)
            for command_path in manifest.cli:
                app.cli.add_command(import_attr(command_path, owner=manifest.name))

        # 4) post-boot validation hooks (run once everything is wired)
        for manifest in order:
            if manifest.post_boot:
                hook = import_attr(manifest.post_boot, owner=manifest.name)
                hook(container, app)

        self._assert_no_url_collisions(app)
        app.extensions["modules"] = {m.name: m.version for m in order}
        _log.info("kernel.boot modules=%s", [m.name for m in order])
        return order

    @staticmethod
    def _assert_no_url_collisions(app: Flask) -> None:
        seen: dict[tuple[str, frozenset[str]], str] = {}
        for rule in app.url_map.iter_rules():
            methods = frozenset((rule.methods or set()) - {"HEAD", "OPTIONS"})
            for method in methods:
                key = (rule.rule, frozenset({method}))
                previous = seen.get(key)
                if previous is not None and previous != rule.endpoint:
                    raise DuplicateRouteError(f"{method} {rule.rule}: '{previous}' and '{rule.endpoint}'")
                seen[key] = rule.endpoint
