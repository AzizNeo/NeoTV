"""titles HTTP adapter: /api/v1/titles (schemas bound payload *shape*; rules live in domain.validate)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Literal

from flask import Blueprint, Response
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.responses import no_content, ok
from app.modules.titles.domain import EpisodeDraft, SeasonDraft, TitleDraft, TitleKind
from app.modules.titles.services import TitleAdminService

blueprint = Blueprint("titles", __name__)

_Rating = Literal["general", "teen", "adult", "unrated"]


# ── Schemas ──────────────────────────────────────────────────────────────────
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EpisodeDoc(_Strict):
    number: int = Field(ge=1, le=9999)
    name: str = Field(min_length=1, max_length=200)
    play_ref: str | None = Field(default=None, max_length=64)
    synopsis: str | None = Field(default=None, max_length=4000)
    runtime_minutes: int | None = None
    still_url: str | None = Field(default=None, max_length=1024)


class SeasonDoc(_Strict):
    number: int = Field(ge=0, le=9999)
    name: str | None = Field(default=None, max_length=200)
    episodes: list[EpisodeDoc] = Field(default_factory=list, max_length=500)


class TitleDocIn(_Strict):
    """A whole title. ``PUT`` replaces the stored aggregate with exactly this document."""

    kind: Literal["movie", "series"]
    name: str = Field(min_length=1, max_length=200)
    rating: _Rating = "unrated"
    synopsis: str | None = Field(default=None, max_length=4000)
    year: int | None = None
    runtime_minutes: int | None = None
    poster_url: str | None = Field(default=None, max_length=1024)
    backdrop_url: str | None = Field(default=None, max_length=1024)
    play_ref: str | None = Field(default=None, max_length=64)
    genres: list[str] = Field(default_factory=list, max_length=8)
    featured_rank: int | None = None
    is_published: bool = True
    seasons: list[SeasonDoc] = Field(default_factory=list, max_length=100)

    def to_draft(self, slug: str) -> TitleDraft:
        return TitleDraft(
            slug=slug,
            kind=TitleKind(self.kind),
            name=self.name,
            rating=self.rating,
            synopsis=self.synopsis,
            year=self.year,
            runtime_minutes=self.runtime_minutes,
            poster_url=self.poster_url,
            backdrop_url=self.backdrop_url,
            play_ref=self.play_ref,
            genres=tuple(g[:80] for g in self.genres),
            featured_rank=self.featured_rank,
            is_published=self.is_published,
            seasons=tuple(
                SeasonDraft(
                    number=s.number,
                    name=s.name,
                    episodes=tuple(EpisodeDraft(**e.model_dump()) for e in s.episodes),
                )
                for s in self.seasons
            ),
        )


class TitleDocOut(TitleDocIn):
    model_config = ConfigDict(extra="forbid")
    slug: str


class AdminListQuery(BaseModel):
    search: str | None = Field(default=None, max_length=100)
    cursor: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=50, ge=1, le=100)


class TitleAdminRowOut(BaseModel):
    slug: str
    kind: str
    name: str
    year: int | None
    is_published: bool
    featured_rank: int | None
    sources: int
    unavailable_sources: int
    updated_at: datetime


class TitleAdminPageOut(BaseModel):
    items: list[TitleAdminRowOut]
    next_cursor: str | None


def _doc(draft: TitleDraft) -> dict[str, object]:
    return TitleDocOut.model_validate(asdict(draft)).model_dump(mode="json")


# ── Administration ───────────────────────────────────────────────────────────
@blueprint.get("/admin/titles")
@endpoint(
    summary="Admin title list with source health",
    permission="titles:write",
    query=AdminListQuery,
    response=TitleAdminPageOut,
)
def admin_list(query: AdminListQuery) -> object:
    return resolve(TitleAdminService).page(search=query.search, after=query.cursor, limit=query.limit)


@blueprint.get("/admin/titles/<string:slug>")
@endpoint(
    summary="The editable title document",
    permission="titles:write",
    response=TitleDocOut,
    errors=("TITLE_NOT_FOUND",),
)
def admin_get(slug: str) -> object:
    return _doc(resolve(TitleAdminService).document(slug))


@blueprint.put("/admin/titles/<string:slug>")
@endpoint(
    summary="Create or replace a title (whole document; 201 when created)",
    permission="titles:write",
    body=TitleDocIn,
    response=TitleDocOut,
    errors=("TITLE_INVALID", "PLAY_SOURCE_NOT_FOUND"),
)
def admin_put(slug: str, body: TitleDocIn) -> Response:
    service = resolve(TitleAdminService)
    created = service.upsert(body.to_draft(slug))
    return ok(_doc(service.document(slug)), status=201 if created else 200)


@blueprint.delete("/admin/titles/<string:slug>")
@endpoint(summary="Delete a title (its sources are untouched)", permission="titles:write", errors=("TITLE_NOT_FOUND",))
def admin_delete(slug: str) -> Response:
    resolve(TitleAdminService).delete(slug)
    return no_content()
