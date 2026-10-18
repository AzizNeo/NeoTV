from __future__ import annotations

import threading
from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.extensions import ExtensionRegistry
from app.kernel.manifest import ExtensionSpec, ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.observability.metrics import Metrics
from app.kernel.security.device_keys import DeviceKeys
from app.kernel.security.egress import EgressGateway
from app.kernel.security.signed_url import UrlSigner
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.playback.api import (
    ContentDirectory,
    GrantVerifier,
    SessionDirectory,
    SessionInactiveError,
    SessionOpener,
    StreamUrlFactory,
)
from app.modules.playback.gate import (
    ContentNotFoundError,
    NoContentProviderError,
    PlaybackConfigurationError,
    PlaybackDeniedError,
)
from app.modules.playback.hls_proxy import UpstreamStatusError, UpstreamUnavailableError
from app.modules.playback.services import SessionExpiredError, StreamLimitExceededError
from app.shared_kernel.events import DeviceRevoked, SubscriptionChanged, UserStatusChanged

POINT_PROVIDERS = "playback.content_providers"
POINT_POLICIES = "playback.policies"
POINT_ENHANCERS = "playback.source_enhancers"


def _gate_factory(c: Any) -> Any:
    """Gate is built lazily on first use (all modules booted by then) and cached."""
    from app.modules.playback.gate import PlaybackGate

    lock = threading.Lock()
    cache: dict[str, PlaybackGate] = {}

    def provide() -> PlaybackGate:
        gate = cache.get("gate")
        if gate is None:
            with lock:
                gate = cache.get("gate")
                if gate is None:
                    extensions = c.resolve(ExtensionRegistry)
                    gate = PlaybackGate(
                        providers=extensions.build(POINT_PROVIDERS, c),
                        policies=extensions.build(POINT_POLICIES, c),
                        enhancers=extensions.build(POINT_ENHANCERS, c),
                    )
                    cache["gate"] = gate
        return gate

    return provide


def _services(c: Any) -> None:
    from app.modules.playback.concurrency import StreamConcurrencyGuard
    from app.modules.playback.gate import ContentDirectoryService
    from app.modules.playback.grants import MediaGrantVerifier, SignedStreamUrlFactory
    from app.modules.playback.hls_proxy import HlsProxyService
    from app.modules.playback.services import PlaybackSessionService, SessionDirectoryService, SessionOpenerService

    c.register(StreamConcurrencyGuard, lambda c: StreamConcurrencyGuard(c.resolve("kernel.redis")))
    c.register(StreamUrlFactory, lambda c: SignedStreamUrlFactory(c.resolve(UrlSigner)))
    c.register(
        GrantVerifier,
        lambda c: MediaGrantVerifier(
            c.resolve(UrlSigner),
            c.resolve(StreamConcurrencyGuard),
            on_media_heartbeat=lambda user_id, token: c.resolve(PlaybackSessionService).touch_record(user_id, token),
        ),
    )
    c.register(
        HlsProxyService,
        lambda c: HlsProxyService(c.resolve(EgressGateway), c.resolve(StreamUrlFactory), c.resolve(Metrics)),
    )
    c.register("playback.gate_provider", _gate_factory)
    c.register(ContentDirectory, lambda c: ContentDirectoryService(c.resolve("playback.gate_provider")))
    c.register(
        PlaybackSessionService,
        lambda c: PlaybackSessionService(
            uow=c.resolve(UnitOfWorkFactory),
            gate_provider=c.resolve("playback.gate_provider"),
            guard=c.resolve(StreamConcurrencyGuard),
            device_keys=c.resolve(DeviceKeys),
            capabilities=c.resolve(CapabilityIndex),
            settings=c.resolve(Settings),
            clock=c.resolve(Clock),
            metrics=c.resolve(Metrics),
        ),
    )
    c.register(
        SessionOpener,
        lambda c: SessionOpenerService(c.resolve(PlaybackSessionService)),
    )
    c.register(
        SessionDirectory,
        lambda c: SessionDirectoryService(
            c.resolve(StreamConcurrencyGuard), c.resolve(PlaybackSessionService), c.resolve(UnitOfWorkFactory)
        ),
    )


manifest = ModuleManifest(
    name="playback",
    version="2.0.0",
    description="Playback gate, concurrent-stream slots, signed media grants, upstream HLS proxy, QoE.",
    provides={
        "playback.urls": StreamUrlFactory,
        "playback.grants": GrantVerifier,
        "playback.content": ContentDirectory,
        "playback.sessions": SessionDirectory,
        "playback.open": SessionOpener,
    },
    requires=frozenset({"identity.authentication", "profile.context"}),
    optional_requires=frozenset({"billing.entitlements"}),
    models=("app.modules.playback.models",),
    services=_services,
    routes=(RouteSpec("app.modules.playback.http:blueprint", "/api/v1/playback"),),
    extension_points=(POINT_PROVIDERS, POINT_POLICIES, POINT_ENHANCERS),
    extensions=(ExtensionSpec(POINT_POLICIES, "app.modules.playback.gate:build_kids_policy"),),
    subscriptions=(
        SubscriptionSpec(
            UserStatusChanged.NAME,
            "playback.release_on_suspend",
            "app.modules.playback.handlers:on_user_status_changed",
        ),
        SubscriptionSpec(
            DeviceRevoked.NAME, "playback.release_on_device_revoke", "app.modules.playback.handlers:on_device_revoked"
        ),
        SubscriptionSpec(
            SubscriptionChanged.NAME,
            "playback.enforce_plan_limit",
            "app.modules.playback.handlers:on_subscription_changed",
        ),
    ),
    task_modules=("app.modules.playback.tasks",),
    beat_schedule={"playback.expire-stale": {"task": "playback.expire_stale_sessions", "schedule": 60.0}},
    error_map={
        StreamLimitExceededError: (403, "STREAM_LIMIT_EXCEEDED"),
        SessionExpiredError: (401, "SESSION_EXPIRED"),
        PlaybackDeniedError: (403, "PLAYBACK_DENIED"),
        ContentNotFoundError: (404, "CONTENT_NOT_FOUND"),
        NoContentProviderError: (404, "CONTENT_PROVIDER_UNAVAILABLE"),
        SessionInactiveError: (403, "SESSION_INACTIVE"),
        UpstreamStatusError: (502, "UPSTREAM_STATUS"),
        UpstreamUnavailableError: (502, "UPSTREAM_UNAVAILABLE"),
        PlaybackConfigurationError: (500, "PLAYBACK_MISCONFIGURED"),
    },
    post_boot="app.modules.playback.post_boot:install_metrics",
)
