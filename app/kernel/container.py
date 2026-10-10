"""Minimal, explicit dependency-injection container (composition root).

* Keys are either a type (preferred — gives IDE navigation) or a namespaced
  string (``"billing.subscriptions"``) for implementation-private services.
* Every registration remembers its **owner** (the module that registered it), so
  conflicts and missing services are reported with a name, never silently.
* Lifetimes: ``singleton`` (process-wide), ``request`` (one instance per Flask
  app context — i.e. per request or per Celery task), ``transient``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal, TypeVar, overload

from flask import current_app, g, has_app_context

T = TypeVar("T")
Key = type | str
Lifetime = Literal["singleton", "request", "transient"]
Factory = Callable[["Container"], Any]

_SCOPE_ATTR = "_di_request_scope"


def key_name(key: Key) -> str:
    return key if isinstance(key, str) else f"{key.__module__}.{key.__qualname__}"


class ServiceNotRegisteredError(LookupError):
    def __init__(self, key: Key) -> None:
        super().__init__(
            f"'{key_name(key)}' is not registered. Check that the module which should provide it is listed "
            f"in INSTALLED_MODULES, is not disabled, and registers it in its manifest `services` hook."
        )
        self.key = key


class DuplicateServiceError(RuntimeError):
    pass


class CircularServiceDependencyError(RuntimeError):
    pass


class RequestScopeUnavailableError(RuntimeError):
    pass


class _Registration:
    __slots__ = ("factory", "lifetime", "owner")

    def __init__(self, factory: Factory, lifetime: Lifetime, owner: str) -> None:
        self.factory = factory
        self.lifetime = lifetime
        self.owner = owner


class Container:
    def __init__(self) -> None:
        self._registrations: dict[Key, _Registration] = {}
        self._singletons: dict[Key, Any] = {}
        self._lock = threading.RLock()
        self._local = threading.local()
        self._owner = "kernel"

    # ── Registration ───────────────────────────────────────────────────────
    @contextmanager
    def owned_by(self, owner: str) -> Iterator[Container]:
        previous, self._owner = self._owner, owner
        try:
            yield self
        finally:
            self._owner = previous

    def register(
        self,
        key: Key,
        factory: Factory,
        *,
        lifetime: Lifetime = "singleton",
        replace: bool = False,
    ) -> None:
        with self._lock:
            existing = self._registrations.get(key)
            if existing is not None and not replace:
                raise DuplicateServiceError(
                    f"'{key_name(key)}' is already registered by '{existing.owner}'; "
                    f"'{self._owner}' tried to register it again"
                )
            self._registrations[key] = _Registration(factory, lifetime, self._owner)
            self._singletons.pop(key, None)

    def register_instance(self, key: Key, instance: Any, *, replace: bool = False) -> None:
        self.register(key, lambda _c: instance, replace=replace)

    def override(self, key: Key, instance: Any) -> None:
        """Test hook: replace whatever is registered with a ready instance."""
        self.register(key, lambda _c: instance, replace=True)

    # ── Introspection ──────────────────────────────────────────────────────
    def has(self, key: Key) -> bool:
        return key in self._registrations

    def owner_of(self, key: Key) -> str:
        try:
            return self._registrations[key].owner
        except KeyError:
            raise ServiceNotRegisteredError(key) from None

    def keys(self) -> list[Key]:
        return list(self._registrations)

    # ── Resolution ─────────────────────────────────────────────────────────
    @overload
    def resolve(self, key: type[T]) -> T: ...
    @overload
    def resolve(self, key: str) -> Any: ...

    def resolve(self, key: Key) -> Any:
        registration = self._registrations.get(key)
        if registration is None:
            raise ServiceNotRegisteredError(key)

        if registration.lifetime == "singleton":
            with self._lock:
                if key not in self._singletons:
                    self._singletons[key] = self._build(key, registration.factory)
                return self._singletons[key]

        if registration.lifetime == "request":
            if not has_app_context():
                raise RequestScopeUnavailableError(
                    f"'{key_name(key)}' is request-scoped and cannot be resolved outside an app context"
                )
            scope: dict[Key, Any] = g.setdefault(_SCOPE_ATTR, {})
            if key not in scope:
                scope[key] = self._build(key, registration.factory)
            return scope[key]

        return self._build(key, registration.factory)

    def _build(self, key: Key, factory: Factory) -> Any:
        stack: tuple[Key, ...] = getattr(self._local, "stack", ())
        if key in stack:
            chain = " → ".join(key_name(k) for k in (*stack, key))
            raise CircularServiceDependencyError(chain)
        self._local.stack = (*stack, key)
        try:
            return factory(self)
        finally:
            self._local.stack = stack


def container() -> Container:
    """The container bound to the current Flask application."""
    return current_app.extensions["container"]


@overload
def resolve(key: type[T]) -> T: ...
@overload
def resolve(key: str) -> Any: ...


def resolve(key: Key) -> Any:
    return container().resolve(key)
