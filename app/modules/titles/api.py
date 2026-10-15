"""PUBLIC surface of the titles module (nothing else in this package may be imported by other modules).

Capability ``titles.admin`` lets another module edit storefront documents through the same
use case — and therefore the same validation and source checks — as the admin API. Metadata
importers (TMDB …) use it; they never touch titles' tables.
"""

from __future__ import annotations

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
    "LocalizedText",
    "SeasonDraft",
    "TitleCatalogAdmin",
    "TitleDraft",
    "TitleKind",
    "TitleNotFoundError",
    "TitlesError",
    "slugify",
]
