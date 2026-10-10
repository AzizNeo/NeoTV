from __future__ import annotations

from typing import Any

from app.kernel.manifest import ExtensionSpec, ModuleManifest, RouteSpec
from app.kernel.resilience.circuit_breaker import CircuitBreakerRegistry
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.catalog.api import CatalogReader
from app.modules.catalog.fetcher import PlaylistFetchError
from app.modules.catalog.services import (
    CatalogAdminService,
    CatalogQueryService,
    CatalogReaderService,
    ChannelNotFoundError,
    DuplicateChannelError,
    PlaylistNotFoundError,
    PlaylistSyncService,
    SystemPlaylistProtectedError,
)


def _services(c: Any) -> None:
    c.register(
        CatalogQueryService,
        lambda c: CatalogQueryService(
            c.resolve(UnitOfWorkFactory), c.resolve(CircuitBreakerRegistry), c.resolve("kernel.redis")
        ),
    )
    c.register(CatalogAdminService, lambda c: CatalogAdminService(c.resolve(UnitOfWorkFactory), c.resolve(Clock)))
    c.register(PlaylistSyncService, lambda c: PlaylistSyncService(c.resolve(UnitOfWorkFactory), c.resolve(Clock)))
    c.register(CatalogReader, lambda c: CatalogReaderService(c.resolve(UnitOfWorkFactory)))


manifest = ModuleManifest(
    name="catalog",
    version="2.0.0",
    description="Channel/VOD catalogue fed by M3U playlists and manual entries.",
    provides={"catalog.read": CatalogReader},
    requires=frozenset({"identity.authentication", "profile.context", "playback.urls"}),
    models=("app.modules.catalog.models",),
    services=_services,
    routes=(RouteSpec("app.modules.catalog.http:blueprint", "/api/v1/catalog"),),
    task_modules=("app.modules.catalog.tasks",),
    task_routes={"catalog.*": {"queue": "playlist"}},
    permissions=("catalog:write",),
    extensions=(ExtensionSpec("playback.content_providers", "app.modules.catalog.provider:build_provider"),),
    error_map={
        ChannelNotFoundError: (404, "CHANNEL_NOT_FOUND"),
        PlaylistNotFoundError: (404, "PLAYLIST_NOT_FOUND"),
        SystemPlaylistProtectedError: (409, "SYSTEM_PLAYLIST_PROTECTED"),
        DuplicateChannelError: (409, "DUPLICATE_CHANNEL"),
        PlaylistFetchError: (502, "PLAYLIST_FETCH_FAILED"),
    },
)
