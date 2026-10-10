"""Kernel building blocks — each failure mode must be a *named* error."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import fakeredis
import pytest

from app.kernel.cache.stampede import CacheComputeTimeoutError, StampedeGuard
from app.kernel.container import (
    CircularServiceDependencyError,
    Container,
    DuplicateServiceError,
    ServiceNotRegisteredError,
)
from app.kernel.errors import (
    CircularModuleDependencyError,
    DisabledDependencyError,
    DuplicateModuleError,
    MissingCapabilityError,
    UnknownExtensionPointError,
    UnknownModuleError,
)
from app.kernel.events.registry import EventRegistry, EventSchemaError, MissingUpcasterError
from app.kernel.extensions import ExtensionRegistry
from app.kernel.manifest import ModuleManifest, SubscriptionSpec
from app.kernel.registry import ModuleRegistry
from app.kernel.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from app.kernel.resilience.rate_limit import GCRARateLimiter
from app.kernel.security.signed_url import SignatureExpiredError, SignatureInvalidError, UrlSigner
from app.shared_kernel.content import ContentRef, InvalidContentRefError

# ── Container ──────────────────────────────────────────────────────────────


class Svc:
    pass


def test_container_named_errors() -> None:
    c = Container()
    with pytest.raises(ServiceNotRegisteredError):
        c.resolve(Svc)
    c.register(Svc, lambda _c: Svc())
    with pytest.raises(DuplicateServiceError):
        c.register(Svc, lambda _c: Svc())
    assert c.resolve(Svc) is c.resolve(Svc)  # singleton
    c.register("a", lambda c: c.resolve("b"))
    c.register("b", lambda c: c.resolve("a"))
    with pytest.raises(CircularServiceDependencyError):
        c.resolve("a")


def test_container_records_owner() -> None:
    c = Container()
    with c.owned_by("billing"):
        c.register(Svc, lambda _c: Svc())
    assert c.owner_of(Svc) == "billing"


def test_transient_lifetime_builds_every_time() -> None:
    c = Container()
    c.register(Svc, lambda _c: Svc(), lifetime="transient")
    assert c.resolve(Svc) is not c.resolve(Svc)


# ── Module registry ────────────────────────────────────────────────────────


def _m(name: str, **kw: Any) -> ModuleManifest:
    return ModuleManifest(name=name, version="1", description=name, **kw)


AUTH = _m("identity", provides={"identity.authentication": object})


def test_registry_orders_by_capability_dependencies() -> None:
    a = _m("a", provides={"a.x": object}, requires=frozenset({"b.y"}))
    b = _m("b", provides={"b.y": object})
    order = [m.name for m in ModuleRegistry([AUTH, a, b]).resolve_order()]
    assert order.index("b") < order.index("a")


def test_registry_missing_capability_is_named() -> None:
    with pytest.raises(MissingCapabilityError):
        ModuleRegistry([AUTH, _m("a", requires=frozenset({"ghost.cap"}))]).resolve_order()


def test_registry_disabled_dependency_is_named() -> None:
    a = _m("a", requires=frozenset({"b.y"}))
    b = _m("b", provides={"b.y": object})
    with pytest.raises(DisabledDependencyError):
        ModuleRegistry([AUTH, a, b], disabled=frozenset({"b"})).resolve_order()


def test_registry_optional_dependency_may_be_disabled() -> None:
    a = _m("a", optional_requires=frozenset({"b.y"}))
    b = _m("b", provides={"b.y": object})
    names = [m.name for m in ModuleRegistry([AUTH, a, b], disabled=frozenset({"b"})).resolve_order()]
    assert names == ["identity", "a"] or set(names) == {"identity", "a"}


def test_registry_cycle_and_duplicates_and_unknown() -> None:
    a = _m("a", provides={"a.x": object}, requires=frozenset({"b.y"}))
    b = _m("b", provides={"b.y": object}, requires=frozenset({"a.x"}))
    with pytest.raises(CircularModuleDependencyError):
        ModuleRegistry([AUTH, a, b]).resolve_order()
    # Capabilities are namespaced by module name, so a duplicate provider can only
    # come from installing the same module twice — rejected by name.
    with pytest.raises(DuplicateModuleError):
        ModuleRegistry([AUTH, _m("c", provides={"c.z": object}), _m("c", provides={"c.z": object})])
    with pytest.raises(UnknownModuleError):
        ModuleRegistry([AUTH], disabled=frozenset({"nope"}))


def test_kernel_requires_authentication_provider() -> None:
    with pytest.raises(MissingCapabilityError):
        ModuleRegistry([_m("a")]).resolve_order()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provides": {"other.cap": object}},
        {"extension_points": ("other.point",)},
        {"permissions": ("no-colon",)},
        {"subscriptions": (SubscriptionSpec("x.y", "other.consumer", "m:f"),)},
        {"requires": frozenset({"b.y"}), "optional_requires": frozenset({"b.y"})},
    ],
)
def test_manifest_rejects_contract_violations(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _m("mod", **kwargs)


def test_extension_point_must_be_declared() -> None:
    ext = ExtensionRegistry()
    with pytest.raises(UnknownExtensionPointError):
        ext.contribute("ghost.point", "a", lambda c: None)
    ext.mark_disabled("off.point")
    ext.contribute("off.point", "a", lambda c: None)  # dropped, not an error (owner disabled)
    ext.declare("p.point", "p")
    ext.contribute("p.point", "z", lambda c: "z")
    ext.contribute("p.point", "a", lambda c: "a")
    assert ext.build("p.point", None) == ["a", "z"]  # deterministic order


# ── Events ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ThingHappened:
    NAME: ClassVar[str] = "test.thing_happened"
    VERSION: ClassVar[int] = 2
    thing_id: int
    label: str


def test_event_registry_upcasts_old_payloads() -> None:
    reg = EventRegistry()
    reg.register(ThingHappened)

    @reg.upcaster("test.thing_happened", from_version=1)
    def v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
        return {**data, "label": "n/a"}

    event = reg.decode("test.thing_happened", 1, '{"thing_id": 7}')
    assert event == ThingHappened(7, "n/a")
    name, version, raw = reg.encode(ThingHappened(1, "x"))
    assert (name, version) == ("test.thing_happened", 2) and reg.decode(name, version, raw) == ThingHappened(1, "x")


def test_event_registry_named_errors() -> None:
    reg = EventRegistry()
    reg.register(ThingHappened)
    with pytest.raises(MissingUpcasterError):
        reg.decode("test.thing_happened", 1, '{"thing_id": 1}')
    with pytest.raises(EventSchemaError):
        reg.decode("test.thing_happened", 3, '{"thing_id": 1, "label": "x"}')
    with pytest.raises(EventSchemaError):
        reg.register(type("NotADataclass", (), {}))


# ── Security / resilience ──────────────────────────────────────────────────


def test_url_signer_binds_subject_target_and_expiry() -> None:
    signer = UrlSigner(b"k" * 32)
    params = signer.sign("https://cdn/a.m3u8", "7.tok", ttl=60)
    assert signer.verify(params).target == "https://cdn/a.m3u8"
    with pytest.raises(SignatureInvalidError):
        signer.verify({**params, "s": "8.tok"})
    with pytest.raises(SignatureInvalidError):
        signer.verify({**params, "u": UrlSigner(b"k" * 32).sign("https://evil", "7.tok")["u"]})
    with pytest.raises(SignatureExpiredError):
        signer.verify(signer.sign("x", "7.tok", expires_at=1))


def test_circuit_breaker_half_open_probe() -> None:
    now = [0.0]
    cb = CircuitBreaker("db", failure_threshold=2, recovery_timeout=10, clock=lambda: now[0])

    def boom() -> None:
        raise OSError("down")

    for _ in range(2):
        with pytest.raises(OSError):
            cb.call(boom)
    assert cb.state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: 1)
    now[0] = 11
    with pytest.raises(OSError):
        cb.call(boom)  # failed probe re-opens
    assert cb.state is CircuitState.OPEN
    now[0] = 22
    assert cb.call(lambda: 5) == 5
    assert cb.state is CircuitState.CLOSED


def test_circuit_breaker_ignores_uncounted_exceptions() -> None:
    cb = CircuitBreaker("x", failure_threshold=1, counted=(OSError,))
    with pytest.raises(KeyError):
        cb.call(lambda: {}["missing"])
    assert cb.state is CircuitState.CLOSED


def test_gcra_rate_limiter_allows_burst_then_limits() -> None:
    limiter = GCRARateLimiter(fakeredis.FakeRedis(server=fakeredis.FakeServer()))
    results = [limiter.allow("k", rps=1, burst=3)[0] for _ in range(5)]
    assert results[:3] == [True, True, True]
    allowed, retry_after = limiter.allow("k", rps=1, burst=3)
    assert not allowed and retry_after > 0


def test_stampede_guard_serves_stale_and_times_out() -> None:
    redis = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    guard = StampedeGuard(redis, namespace="t", ttl=60, stale_ttl=60, wait_budget=0.1)
    assert guard.get_or_compute("k", lambda: [1, 2]) == [1, 2]
    assert guard.get_or_compute("k", lambda: pytest.fail("cached value must be reused")) == [1, 2]
    redis.set("t:lock:other", "someone-else")
    with pytest.raises(CacheComputeTimeoutError):
        guard.get_or_compute("other", lambda: 1)


@pytest.mark.parametrize("raw", ["catalog", "catalog:", "catalog:x", "Catalog:1", "catalog:0", ":1"])
def test_content_ref_rejects_malformed(raw: str) -> None:
    with pytest.raises(InvalidContentRefError):
        ContentRef.parse(raw)


def test_content_ref_roundtrip() -> None:
    assert str(ContentRef.parse("live:12")) == "live:12"
