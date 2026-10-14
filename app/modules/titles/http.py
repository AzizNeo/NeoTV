"""titles HTTP adapter: /api/v1/titles (schemas bound payload *shape*; rules live in domain.validate)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Literal

from flask import Blueprint, Response
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.locale import request_locale, vary_on_language
from app.kernel.http.profile_context import current_profile
from app.kernel.http.responses import no_content, ok
from app.kernel.resilience.rate_limit import Rate
from app.modules.titles.domain import EpisodeDraft, LocalizedText, SeasonDraft, TitleDraft, TitleKind
from app.modules.titles.queries import TitleQuery, TitleQueryService
from app.modules.titles.services import TitleAdminService

blueprint = Blueprint("titles", __name__)
blueprint.after_request(vary_on_language)  # names and synopses follow Accept-Language

_Rating = Literal["general", "teen", "adult", "unrated"]


# ── Schemas ──────────────────────────────────────────────────────────────────
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TextDoc(_Strict):
    """A translation: the original text is the document's own ``name`` / ``synopsis``."""

    name: str = Field(min_length=1, max_length=200)
    synopsis: str | None = Field(default=None, max_length=4000)


#: locale → translation (``{"en": {...}}``); languages are checked by the domain (named problems).
_Translations = dict[str, TextDoc]


def _texts(translations: _Translations) -> dict[str, LocalizedText]:
    return {locale: LocalizedText(name=t.name, synopsis=t.synopsis) for locale, t in translations.items()}


class EpisodeDoc(_Strict):
    number: int = Field(ge=1, le=9999)
    name: str = Field(min_length=1, max_length=200)
    play_ref: str | None = Field(default=None, max_length=64)
    synopsis: str | None = Field(default=None, max_length=4000)
    runtime_minutes: int | None = None
    still_url: str | None = Field(default=None, max_length=1024)
    translations: _Translations = Field(default_factory=dict, max_length=4)

    def to_draft(self) -> EpisodeDraft:
        data = self.model_dump(exclude={"translations"})
        return EpisodeDraft(**data, translations=_texts(self.translations))


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
    translations: _Translations = Field(default_factory=dict, max_length=4)

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
            translations=_texts(self.translations),
            seasons=tuple(
                SeasonDraft(
                    number=s.number,
                    name=s.name,
                    episodes=tuple(e.to_draft() for e in s.episodes),
                )
                for s in self.seasons
            ),
        )


class TitleDocOut(TitleDocIn):
    model_config = ConfigDict(extra="forbid")
    slug: str


class GenreNamesIn(_Strict):
    names: dict[str, str] = Field(max_length=4, description='locale → translated name, e.g. {"en": "Action"}')


class GenreNamesOut(BaseModel):
    slug: str
    name: str
    names: dict[str, str]


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


class BrowseQuery(BaseModel):
    kind: Literal["movie", "series"] | None = None
    genre: str | None = Field(default=None, max_length=80)
    search: str | None = Field(default=None, max_length=100)
    year_from: int | None = Field(default=None, ge=1888, le=2100)
    year_to: int | None = Field(default=None, ge=1888, le=2100)
    sort: Literal["recent", "name", "year"] = "recent"
    page: int = Field(default=1, ge=1, le=10_000)
    per_page: int = Field(default=24, ge=1, le=100)


class RailsQuery(BaseModel):
    genres: int = Field(default=6, ge=1, le=20)
    per_rail: int = Field(default=12, ge=1, le=30)


class FeaturedQuery(BaseModel):
    limit: int = Field(default=5, ge=1, le=10)


class TitleCardOut(BaseModel):
    slug: str
    kind: str
    name: str
    year: int | None
    rating: str
    runtime_minutes: int | None
    season_count: int
    genres: list[str]
    poster_url: str | None
    backdrop_url: str | None
    available: bool


class TitlePageOut(BaseModel):
    items: list[TitleCardOut]
    total: int
    page: int
    per_page: int


class GenreOut(BaseModel):
    slug: str
    name: str
    count: int


class RailOut(BaseModel):
    genre: GenreOut
    items: list[TitleCardOut]


class FeaturedOut(BaseModel):
    card: TitleCardOut
    synopsis: str | None
    play_ref: str | None


class EpisodeOut(BaseModel):
    number: int
    name: str
    synopsis: str | None
    runtime_minutes: int | None
    still_url: str | None
    play_ref: str | None
    available: bool


class SeasonOut(BaseModel):
    number: int
    name: str | None
    episodes: list[EpisodeOut]


class GenreLinkOut(BaseModel):
    slug: str
    name: str


class TitleDetailOut(BaseModel):
    card: TitleCardOut
    synopsis: str | None
    play_ref: str | None
    seasons: list[SeasonOut]
    genre_links: list[GenreLinkOut]


def _kids() -> bool:
    return current_profile().is_kids


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
    errors=("TITLE_INVALID", "PLAY_SOURCE_NOT_FOUND", "TITLE_RATING_CONFLICT"),
)
def admin_put(slug: str, body: TitleDocIn) -> Response:
    service = resolve(TitleAdminService)
    created = service.upsert(body.to_draft(slug))
    return ok(_doc(service.document(slug)), status=201 if created else 200)


@blueprint.put("/admin/genres/<string:slug>")
@endpoint(
    summary="Set a genre's translated names (titles keep the original)",
    permission="titles:write",
    body=GenreNamesIn,
    response=GenreNamesOut,
    errors=("TITLE_NOT_FOUND", "TITLE_INVALID"),
)
def admin_genre_names(slug: str, body: GenreNamesIn) -> object:
    return resolve(TitleAdminService).set_genre_names(slug, body.names)


@blueprint.delete("/admin/titles/<string:slug>")
@endpoint(summary="Delete a title (its sources are untouched)", permission="titles:write", errors=("TITLE_NOT_FOUND",))
def admin_delete(slug: str) -> Response:
    resolve(TitleAdminService).delete(slug)
    return no_content()


# ── Browsing (profile-aware: a kids profile sees only what it may play) ───────
_BROWSE_RATE = Rate("titles.browse", rps=10, burst=30)


@blueprint.get("")
@endpoint(
    summary="Browse titles (filters, search, sort)",
    profile=True,
    query=BrowseQuery,
    response=TitlePageOut,
    rate=_BROWSE_RATE,
)
def browse(query: BrowseQuery) -> object:
    return resolve(TitleQueryService).page(
        TitleQuery(
            kids_only=_kids(),
            kind=TitleKind(query.kind) if query.kind else None,
            genre=query.genre,
            search=query.search,
            year_from=query.year_from,
            year_to=query.year_to,
            sort=query.sort,
            page=query.page,
            per_page=query.per_page,
            locale=request_locale(),
        )
    )


@blueprint.get("/genres")
@endpoint(summary="Genres with title counts", profile=True, response=list[GenreOut])
def genres() -> object:
    return resolve(TitleQueryService).genres(kids_only=_kids(), locale=request_locale())


@blueprint.get("/rails")
@endpoint(
    summary="Home rows: biggest genres with their titles",
    profile=True,
    query=RailsQuery,
    response=list[RailOut],
    rate=_BROWSE_RATE,
)
def rails(query: RailsQuery) -> object:
    return resolve(TitleQueryService).rails(
        kids_only=_kids(), genres=query.genres, per_rail=query.per_rail, locale=request_locale()
    )


@blueprint.get("/featured")
@endpoint(
    summary="Hero titles (playable only, by featured rank)",
    profile=True,
    query=FeaturedQuery,
    response=list[FeaturedOut],
)
def featured(query: FeaturedQuery) -> object:
    return resolve(TitleQueryService).featured(kids_only=_kids(), limit=query.limit, locale=request_locale())


@blueprint.get("/<string:slug>")
@endpoint(
    summary="Title detail with seasons and episodes", profile=True, response=TitleDetailOut, errors=("TITLE_NOT_FOUND",)
)
def detail(slug: str) -> object:
    return resolve(TitleQueryService).detail(slug, kids_only=_kids(), locale=request_locale())
