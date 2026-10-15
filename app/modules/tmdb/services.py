"""TMDB import use cases: search, link (import into a title), refresh, unlink."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.titles.api import TitleCatalogAdmin, TitleDraft, TitleKind, TitleNotFoundError, slugify
from app.modules.tmdb.client import TmdbClient
from app.modules.tmdb.domain import SearchHit, TmdbLinkNotFoundError, merge
from app.modules.tmdb.models import TmdbLink
from app.shared_kernel.locale import DEFAULT_LOCALE


@dataclass(frozen=True, slots=True)
class LinkView:
    slug: str
    tmdb_id: int
    kind: str
    synced_at: datetime
    created: bool = False


class TmdbService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        client: TmdbClient,
        titles: TitleCatalogAdmin,
        configured: bool,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._client = client
        self._titles = titles
        self.configured = configured

    def search(self, query: str, kind: TitleKind, *, year: int | None, locale: str) -> list[SearchHit]:
        return self._client.search(query.strip(), kind, year=year, locale=locale)

    def link(self, slug: str, tmdb_id: int, kind: TitleKind, *, play_ref: str | None = None) -> LinkView:
        """Import TMDB metadata into ``slug`` (creating it when it does not exist) and remember the link."""
        meta = self._client.details(tmdb_id, kind)  # network first: no transaction held open meanwhile
        existing = self._existing(slug)
        draft = merge(existing, slug, meta, original=DEFAULT_LOCALE, play_ref=play_ref)
        created = self._titles.upsert(draft)
        for genre in meta.genres:
            others = {loc: name for loc, name in genre.names.items() if loc != DEFAULT_LOCALE}
            original = genre.names.get(DEFAULT_LOCALE)
            if original and others:
                self._titles.set_genre_names(slugify(original), others)
        with self._uow() as uow:
            link = uow.session.get(TmdbLink, slug) or TmdbLink(title_slug=slug)
            link.tmdb_id, link.kind, link.synced_at = tmdb_id, str(kind), self._clock.now()
            uow.session.add(link)
            return LinkView(slug, tmdb_id, str(kind), link.synced_at, created)

    def refresh(self, slug: str) -> LinkView:
        link = self.get_link(slug)
        return self.link(slug, link.tmdb_id, TitleKind(link.kind))

    def get_link(self, slug: str) -> LinkView:
        with self._uow() as uow:
            link = uow.session.get(TmdbLink, slug)
            if link is None:
                raise TmdbLinkNotFoundError(f"'{slug}' is not linked to TMDB")
            return LinkView(link.title_slug, link.tmdb_id, link.kind, link.synced_at)

    def links(self) -> list[LinkView]:
        with self._uow() as uow:
            rows = uow.session.execute(select(TmdbLink).order_by(TmdbLink.title_slug)).scalars()
            return [LinkView(r.title_slug, r.tmdb_id, r.kind, r.synced_at) for r in rows]

    def unlink(self, slug: str) -> None:
        """Forget the link; the title keeps the metadata it already has."""
        with self._uow() as uow:
            link = uow.session.get(TmdbLink, slug)
            if link is None:
                raise TmdbLinkNotFoundError(f"'{slug}' is not linked to TMDB")
            uow.session.delete(link)

    def _existing(self, slug: str) -> TitleDraft | None:
        try:
            return self._titles.document(slug)
        except TitleNotFoundError:
            return None
