"""Kernel service registration and HTTP/observability installation."""

from __future__ import annotations

from flask import Flask, Response

from app.kernel.cache.stampede import CacheComputeTimeoutError
from app.kernel.capabilities import CapabilityIndex
from app.kernel.container import Container
from app.kernel.events.bus import EventBus
from app.kernel.events.registry import EventRegistry
from app.kernel.extensions import ExtensionRegistry
from app.kernel.http.errors import ErrorMap, install_error_handlers
from app.kernel.http.profile_context import ProfileContextMissingError
from app.kernel.observability.logging import configure_logging
from app.kernel.observability.metrics import Metrics, install_metrics
from app.kernel.observability.tracing import install_tracing
from app.kernel.outbox.metrics import install_outbox_metrics
from app.kernel.redis import build_redis
from app.kernel.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitOpenError
from app.kernel.resilience.locks import LockFactory, LockNotAcquiredError
from app.kernel.resilience.rate_limit import GCRARateLimiter
from app.kernel.security.device_keys import DeviceKeys
from app.kernel.security.egress import (
    EgressBodyTooLargeError,
    EgressDeniedError,
    EgressGateway,
    EgressNetworkError,
    EgressPolicy,
)
from app.kernel.security.permissions import PermissionCatalog
from app.kernel.security.signed_url import SignatureExpiredError, SignatureInvalidError, UrlSigner
from app.kernel.security.tokens import TokenInvalidError, TokenService, TokenType
from app.kernel.settings import Settings
from app.kernel.task_tracking import TaskTracker
from app.kernel.time import Clock, SystemClock
from app.kernel.uow import UnitOfWorkFactory
from app.shared_kernel.content import InvalidContentRefError
from app.shared_kernel.events import ALL_EVENTS

KERNEL = "kernel"


def register_kernel_services(container: Container, settings: Settings) -> None:
    with container.owned_by(KERNEL):
        container.register_instance(Settings, settings)
        container.register(Clock, lambda _c: SystemClock())
        container.register(CapabilityIndex, lambda c: CapabilityIndex(c))
        container.register("kernel.redis", lambda _c: build_redis(settings.redis_url))
        container.register(EventBus, lambda _c: EventBus())
        container.register(EventRegistry, _event_registry)
        container.register(ErrorMap, lambda _c: ErrorMap())
        container.register(ExtensionRegistry, lambda _c: ExtensionRegistry())
        container.register(PermissionCatalog, lambda _c: PermissionCatalog())
        container.register(UnitOfWorkFactory, lambda c: UnitOfWorkFactory(c.resolve(EventRegistry)))
        container.register(
            TokenService,
            lambda _c: TokenService(
                keys={t: settings.derive_key(f"jwt/{t.value}") for t in TokenType},
                ttl={
                    TokenType.ACCESS: settings.access_token_ttl_s,
                    TokenType.PROFILE: settings.profile_token_ttl_s,
                    TokenType.PLAYBACK: settings.playback_grant_ttl_s,
                },
            ),
        )
        container.register(
            UrlSigner,
            lambda _c: UrlSigner(settings.derive_key("media-grants"), default_ttl=settings.playback_grant_ttl_s),
        )
        container.register(
            EgressGateway,
            lambda _c: EgressGateway(
                EgressPolicy(
                    allowed_ports=settings.egress_ports,
                    insecure_tls_hosts=frozenset(h.lower() for h in settings.egress_insecure_tls_hosts),
                )
            ),
        )
        container.register(DeviceKeys, lambda _c: DeviceKeys(settings.derive_key("device-keys")))
        container.register(GCRARateLimiter, lambda c: GCRARateLimiter(c.resolve("kernel.redis")))
        container.register(LockFactory, lambda c: LockFactory(c.resolve("kernel.redis")))
        container.register(CircuitBreakerRegistry, lambda _c: CircuitBreakerRegistry())
        container.register(Metrics, lambda _c: Metrics())
        container.register(TaskTracker, lambda c: TaskTracker(c.resolve("kernel.redis")))


def _event_registry(_c: Container) -> EventRegistry:
    registry = EventRegistry()
    for event_type in ALL_EVENTS:
        registry.register(event_type)
    return registry


def register_kernel_error_mappings(error_map: ErrorMap) -> None:
    mappings: list[tuple[type[BaseException], int, str]] = [
        (CircuitOpenError, 503, "SERVICE_DEGRADED"),
        (CacheComputeTimeoutError, 503, "TEMPORARILY_UNAVAILABLE"),
        (EgressDeniedError, 502, "EGRESS_DENIED"),
        (EgressBodyTooLargeError, 502, "UPSTREAM_TOO_LARGE"),
        (EgressNetworkError, 502, "UPSTREAM_UNREACHABLE"),
        (SignatureInvalidError, 403, "GRANT_INVALID"),
        (SignatureExpiredError, 403, "GRANT_EXPIRED"),
        (TokenInvalidError, 401, "TOKEN_INVALID"),
        (LockNotAcquiredError, 409, "OPERATION_IN_PROGRESS"),
        (InvalidContentRefError, 400, "INVALID_CONTENT_REF"),
        (ProfileContextMissingError, 500, "PROFILE_CONTEXT_MISCONFIGURED"),
    ]
    for exception, status, code in mappings:
        error_map.register(exception, status=status, code=code, owner=KERNEL)


def install_kernel(app: Flask, container: Container, settings: Settings) -> None:
    from app.kernel import task_tracking
    from app.kernel.http import health, request_context
    from app.kernel.outbox import trigger

    configure_logging(level=settings.log_level, json_output=settings.json_logs)
    install_tracing(endpoint=settings.otel_endpoint)
    request_context.install(
        app,
        allowed_origins=list(settings.allowed_origins),
        trusted_proxy_count=settings.trusted_proxy_count,
        hsts_max_age_s=settings.hsts_max_age_s,
    )
    error_map = container.resolve(ErrorMap)
    register_kernel_error_mappings(error_map)
    install_error_handlers(app, error_map)
    app.register_blueprint(health.blueprint, url_prefix="/api/v1/health")
    app.register_blueprint(task_tracking.blueprint, url_prefix="/api/v1/tasks")
    metrics = container.resolve(Metrics)
    install_metrics(app, metrics, token=settings.metrics_token.get_secret_value() if settings.metrics_token else None)
    breakers = container.resolve(CircuitBreakerRegistry)

    def _collect_breakers() -> None:
        for name, state in breakers.snapshot().items():
            metrics.circuit_open.labels(name).set(1 if state == "open" else 0)

    metrics.add_collector(_collect_breakers)
    install_outbox_metrics(metrics, container.resolve(UnitOfWorkFactory), container.resolve(Clock))

    # Breakers live in each worker's memory: every worker publishes its own state after each request
    # (a few dict reads), so a scrape merged across workers (livemax) never misses an open circuit.
    @app.after_request
    def _publish_breakers(response: Response) -> Response:
        _collect_breakers()
        return response

    trigger.install(app)
