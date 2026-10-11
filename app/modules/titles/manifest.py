from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.manifest import ModuleManifest, RouteSpec
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.titles.domain import InvalidTitleError, PlaySourceNotFoundError, TitleNotFoundError


def _services(c: Any) -> None:
    from app.modules.titles.services import TitleAdminService

    c.register(
        TitleAdminService,
        lambda c: TitleAdminService(
            c.resolve(UnitOfWorkFactory), c.resolve(Clock), c.resolve(CapabilityIndex).required("playback.content")
        ),
    )


manifest = ModuleManifest(
    name="titles",
    version="0.1.0",
    description="Storefront metadata over playable content: movies, series → seasons → episodes, genres, artwork.",
    requires=frozenset({"identity.authentication", "profile.context", "playback.content"}),
    models=("app.modules.titles.models",),
    services=_services,
    routes=(RouteSpec("app.modules.titles.http:blueprint", "/api/v1/titles"),),
    permissions=("titles:write",),
    error_map={
        TitleNotFoundError: (404, "TITLE_NOT_FOUND"),
        InvalidTitleError: (422, "TITLE_INVALID"),
        PlaySourceNotFoundError: (422, "PLAY_SOURCE_NOT_FOUND"),
    },
)
