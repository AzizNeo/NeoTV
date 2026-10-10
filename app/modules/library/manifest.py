from __future__ import annotations

from typing import Any

from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.library.api import LibrarySignals
from app.modules.library.services import FavoriteLimitReachedError, LibraryContentNotFoundError
from app.modules.playback.api import ContentDirectory
from app.shared_kernel.events import ContentRemoved, PlaybackSessionEnded, ProfileDeleted


def _services(c: Any) -> None:
    from app.modules.library.services import LibraryService, LibrarySignalsService

    c.register(
        LibraryService,
        lambda c: LibraryService(c.resolve(UnitOfWorkFactory), c.resolve(ContentDirectory), c.resolve(Clock)),
    )
    c.register(LibrarySignals, lambda c: LibrarySignalsService(c.resolve(LibraryService)))


manifest = ModuleManifest(
    name="library",
    version="2.0.0",
    description="Per-profile favourites, resume positions and watch history (content-type agnostic).",
    provides={"library.signals": LibrarySignals},
    requires=frozenset({"identity.authentication", "profile.context", "playback.content"}),
    models=("app.modules.library.models",),
    services=_services,
    routes=(RouteSpec("app.modules.library.http:blueprint", "/api/v1/library"),),
    subscriptions=(
        SubscriptionSpec(
            PlaybackSessionEnded.NAME,
            "library.record_history",
            "app.modules.library.handlers:on_playback_session_ended",
        ),
        SubscriptionSpec(
            ContentRemoved.NAME, "library.purge_content", "app.modules.library.handlers:on_content_removed"
        ),
        SubscriptionSpec(
            ProfileDeleted.NAME, "library.purge_profile", "app.modules.library.handlers:on_profile_deleted"
        ),
    ),
    task_modules=("app.modules.library.tasks",),
    beat_schedule={"library.purge-history": {"task": "library.purge_old_history", "schedule": 86_400.0}},
    error_map={
        LibraryContentNotFoundError: (404, "LIBRARY_CONTENT_NOT_FOUND"),
        FavoriteLimitReachedError: (409, "FAVORITE_LIMIT_REACHED"),
    },
)
