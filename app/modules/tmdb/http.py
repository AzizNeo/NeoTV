"""tmdb HTTP adapter: /api/v1/tmdb — admin only (permission ``titles:write``)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from flask import Blueprint, Response
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.locale import request_locale
from app.kernel.http.responses import no_content, ok
from app.kernel.resilience.rate_limit import Rate
from app.modules.titles.api import TitleKind
from app.modules.tmdb.domain import TmdbNotConfiguredError
from app.modules.tmdb.services import TmdbService

blueprint = Blueprint("tmdb", __name__)
_PERMISSION = "titles:write"
# TMDB allows ~50 requests/s per IP; one admin click can fan out into several calls.
_RATE = Rate("tmdb.admin", rps=2, burst=10)


class StatusOut(BaseModel):
    configured: bool
    attribution: str = "This product uses the TMDB API but is not endorsed or certified by TMDB."


class SearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    kind: Literal["movie", "series"] = "movie"
    year: int | None = Field(default=None, ge=1888, le=2100)


class HitOut(BaseModel):
    tmdb_id: int
    kind: str
    name: str
    original_name: str
    year: int | None
    overview: str | None
    poster_url: str | None


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tmdb_id: int = Field(ge=1)
    kind: Literal["movie", "series"]
    play_ref: str | None = Field(default=None, max_length=64, description="New movies only: what plays")


class LinkOut(BaseModel):
    slug: str
    tmdb_id: int
    kind: str
    synced_at: datetime
    created: bool = False


def _configured() -> TmdbService:
    service = resolve(TmdbService)
    if not service.configured:
        raise TmdbNotConfiguredError("TMDB_READ_TOKEN is not set")
    return service


@blueprint.get("/status")
@endpoint(
    summary="Is the TMDB importer configured? (+ the attribution TMDB requires)",
    permission=_PERMISSION,
    response=StatusOut,
)
def status() -> StatusOut:
    return StatusOut(configured=resolve(TmdbService).configured)


@blueprint.get("/search")
@endpoint(
    summary="Search TMDB (in the admin's language)",
    permission=_PERMISSION,
    query=SearchQuery,
    response=list[HitOut],
    rate=_RATE,
    errors=("METADATA_PROVIDER_NOT_CONFIGURED", "METADATA_PROVIDER_UNAVAILABLE"),
)
def search(query: SearchQuery) -> object:
    return _configured().search(query.query, TitleKind(query.kind), year=query.year, locale=request_locale())


@blueprint.get("/links")
@endpoint(summary="Titles linked to TMDB", permission=_PERMISSION, response=list[LinkOut])
def links() -> object:
    return resolve(TmdbService).links()


@blueprint.put("/links/<string:slug>")
@endpoint(
    summary="Import TMDB metadata into a title (created as a draft when new) and keep the link",
    permission=_PERMISSION,
    body=LinkIn,
    response=LinkOut,
    rate=_RATE,
    errors=(
        "METADATA_PROVIDER_NOT_CONFIGURED",
        "METADATA_PROVIDER_UNAVAILABLE",
        "METADATA_NOT_FOUND",
        "METADATA_KIND_MISMATCH",
        "TITLE_INVALID",
        "PLAY_SOURCE_NOT_FOUND",
        "TITLE_RATING_CONFLICT",
    ),
)
def link(slug: str, body: LinkIn) -> Response:
    view = _configured().link(slug, body.tmdb_id, TitleKind(body.kind), play_ref=body.play_ref)
    return ok(
        LinkOut.model_validate(view, from_attributes=True).model_dump(mode="json"), status=201 if view.created else 200
    )


@blueprint.post("/links/<string:slug>/refresh")
@endpoint(
    summary="Re-import a linked title from TMDB",
    permission=_PERMISSION,
    response=LinkOut,
    rate=_RATE,
    errors=("METADATA_LINK_NOT_FOUND", "METADATA_PROVIDER_NOT_CONFIGURED", "METADATA_PROVIDER_UNAVAILABLE"),
)
def refresh(slug: str) -> object:
    return _configured().refresh(slug)


@blueprint.delete("/links/<string:slug>")
@endpoint(
    summary="Forget the TMDB link (the title keeps its metadata)",
    permission=_PERMISSION,
    errors=("METADATA_LINK_NOT_FOUND",),
)
def unlink(slug: str) -> Response:
    resolve(TmdbService).unlink(slug)
    return no_content()
