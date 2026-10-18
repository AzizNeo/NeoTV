"""PUBLIC surface of the titles module (nothing else in this package may be imported by other modules).

Capability ``titles.admin`` lets another module edit storefront documents through the same
use case — and therefore the same validation and source checks — as the admin API. Metadata
importers (TMDB …) use it; they never touch titles' tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.titles.domain import (
    NAMESPACE,
    EpisodeDraft,
    LocalizedText,
    SeasonDraft,
    TitleDraft,
    TitleKind,
    TitleNotFoundError,
    TitlesError,
    slugify,
)


@dataclass(frozen=True, slots=True)
class EpisodeListing:
    id: int
    season: int
    number: int
    name: str
    synopsis: str | None
    runtime_minutes: int | None
    still_url: str | None
    play_ref: str  # only playable episodes are listed
    added_at: datetime


@dataclass(frozen=True, slots=True)
class TitleListing:
    """A published, playable title as other modules may list it, in the requested language."""

    id: int
    slug: str
    kind: str
    name: str
    synopsis: str | None
    year: int | None
    rating: str
    runtime_minutes: int | None
    genres: tuple[str, ...]
    poster_url: str | None
    backdrop_url: str | None
    play_ref: str | None  # movies: what plays; series: None (their episodes play)
    added_at: datetime
    updated_at: datetime
    episodes: tuple[EpisodeListing, ...] = ()  # series: filled by ``series`` only


class TitleCatalogReader(Protocol):
    """Capability ``titles.read``: the storefront as other front ends (TV apps …) list it.

    Same visibility as the storefront: published titles only, kids ratings only for a kids
    profile, and only what can be played right now.
    """

    def listing(self, *, kind: TitleKind, kids_only: bool, locale: str) -> list[TitleListing]: ...
    def movie_by_ref(self, play_ref: str, *, kids_only: bool, locale: str) -> TitleListing | None: ...
    def series(self, title_id: int, *, kids_only: bool, locale: str) -> TitleListing | None:
        """A series with its playable episodes (season order, then number)."""
        ...


class TitleCatalogAdmin(Protocol):
    """Capability ``titles.admin``."""

    def document(self, slug: str) -> TitleDraft:
        """The editable document; raises ``TitleNotFoundError``."""

    def upsert(self, draft: TitleDraft) -> bool:
        """Validate and replace the whole title; ``True`` when created. Raises ``TitlesError`` subclasses."""

    def set_genre_names(self, slug: str, names: dict[str, str]) -> object:
        """Translated names of a genre (by slug, see :func:`slugify`); ``TitleNotFoundError`` if unknown."""


__all__ = [
    "NAMESPACE",
    "EpisodeDraft",
    "EpisodeListing",
    "LocalizedText",
    "SeasonDraft",
    "TitleCatalogAdmin",
    "TitleCatalogReader",
    "TitleDraft",
    "TitleKind",
    "TitleListing",
    "TitleNotFoundError",
    "TitlesError",
    "slugify",
]
