from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.manifest import ModuleManifest, RouteSpec
from app.kernel.security.egress import EgressGateway
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.tmdb.domain import (
    TmdbKindMismatchError,
    TmdbLinkNotFoundError,
    TmdbNotConfiguredError,
    TmdbNotFoundError,
    TmdbUnavailableError,
)


def _services(c: Any) -> None:
    from app.modules.tmdb.client import EgressTransport, TmdbClient
    from app.modules.tmdb.services import TmdbService

    def token() -> str | None:
        secret = c.resolve(Settings).tmdb_read_token
        return secret.get_secret_value() if secret else None

    c.register(
        TmdbClient, lambda c: TmdbClient(EgressTransport(c.resolve(EgressGateway), token), c.resolve("kernel.redis"))
    )
    c.register(
        TmdbService,
        lambda c: TmdbService(
            c.resolve(UnitOfWorkFactory),
            c.resolve(Clock),
            c.resolve(TmdbClient),
            c.resolve(CapabilityIndex).required("titles.admin"),
            configured=bool(token()),
        ),
    )


manifest = ModuleManifest(
    name="tmdb",
    version="0.1.0",
    description="Imports titles' metadata (names, synopses, artwork, genres, episodes; TR + EN) from TMDB.",
    requires=frozenset({"identity.authentication", "titles.admin"}),
    models=("app.modules.tmdb.models",),
    services=_services,
    routes=(RouteSpec("app.modules.tmdb.http:blueprint", "/api/v1/tmdb"),),
    error_map={
        TmdbNotConfiguredError: (503, "METADATA_PROVIDER_NOT_CONFIGURED"),
        TmdbUnavailableError: (503, "METADATA_PROVIDER_UNAVAILABLE"),
        TmdbNotFoundError: (404, "METADATA_NOT_FOUND"),
        TmdbKindMismatchError: (409, "METADATA_KIND_MISMATCH"),
        TmdbLinkNotFoundError: (404, "METADATA_LINK_NOT_FOUND"),
    },
)
