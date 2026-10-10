from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.playback.api import ContentDirectory
from app.modules.recommendations.api import TrendingReader
from app.shared_kernel.events import ContentRemoved, PlaybackSessionStarted, ProfileDeleted


def _services(c: Any) -> None:
    from app.kernel.cache.stampede import StampedeGuard
    from app.modules.recommendations.services import RecommendationService

    c.register(
        RecommendationService,
        lambda c: RecommendationService(
            uow=c.resolve(UnitOfWorkFactory),
            content=c.resolve(ContentDirectory),
            capabilities=c.resolve(CapabilityIndex),
            trending_guard=StampedeGuard(c.resolve("kernel.redis"), namespace="reco", ttl=300, stale_ttl=3600),
            redis=c.resolve("kernel.redis"),
            clock=c.resolve(Clock),
        ),
    )
    c.register(TrendingReader, lambda c: c.resolve(RecommendationService))


manifest = ModuleManifest(
    name="recommendations",
    version="2.0.0",
    description="Event-fed read model: trending, personalised rows, because-you-watched.",
    provides={"recommendations.trending": TrendingReader},
    requires=frozenset({"identity.authentication", "profile.context", "playback.content"}),
    optional_requires=frozenset({"catalog.read", "library.signals"}),
    models=("app.modules.recommendations.models",),
    services=_services,
    routes=(RouteSpec("app.modules.recommendations.http:blueprint", "/api/v1/recommendations"),),
    subscriptions=(
        SubscriptionSpec(
            PlaybackSessionStarted.NAME,
            "recommendations.count_play",
            "app.modules.recommendations.handlers:on_playback_session_started",
        ),
        SubscriptionSpec(
            ContentRemoved.NAME,
            "recommendations.purge_content",
            "app.modules.recommendations.handlers:on_content_removed",
        ),
        SubscriptionSpec(
            ProfileDeleted.NAME,
            "recommendations.purge_profile",
            "app.modules.recommendations.handlers:on_profile_deleted",
        ),
    ),
    task_modules=("app.modules.recommendations.tasks",),
    beat_schedule={
        "recommendations.purge-buckets": {"task": "recommendations.purge_old_buckets", "schedule": 86_400.0}
    },
)
