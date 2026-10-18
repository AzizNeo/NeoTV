"""What an Xtream app lists: other modules' catalogues mapped to the protocol's shapes.

Read through capabilities only (``catalog.read``, optional ``live.read`` and ``titles.read``), with
the profile's kids filter applied by the owning module — the same rule as the web storefront.
Movies and series are the storefront's titles (curated, with artwork and synopses) in the
account's language; their categories are the titles' genres.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.kernel.db import dialect_insert
from app.kernel.uow import UnitOfWorkFactory
from app.modules.catalog.api import CatalogReader
from app.modules.live.api import LiveReader
from app.modules.titles.api import TitleCatalogReader, TitleKind, TitleListing
from app.modules.xtream import protocol
from app.modules.xtream.domain import XtreamPrincipal
from app.modules.xtream.models import XtreamCategory

ADULT = "adult"


class XtreamCatalog:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        catalog: CatalogReader,
        live: LiveReader | None,
        titles: TitleCatalogReader | None,
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._live = live
        self._titles = titles

    # ── live ──────────────────────────────────────────────────────────────

    def live_categories(self, who: XtreamPrincipal) -> list[dict[str, Any]]:
        names = self._live_category_names(who)
        ids = self.category_ids("live", names)
        return [protocol.category(ids[name], name) for name in names]

    def live_streams(self, who: XtreamPrincipal, *, category_id: str | None = None) -> list[dict[str, Any]]:
        channels = self._catalog.listing(kind="live", kids_only=who.is_kids)
        own = self._live.listing(kids_only=who.is_kids) if self._live is not None else []
        ids = self.category_ids("live", self._live_category_names(who, channels=channels, own=own))
        rows: list[dict[str, Any]] = [
            {
                "ref": c.ref,
                "name": c.name,
                "icon": c.logo,
                "category_id": ids[c.group],
                "epg_channel_id": None,
                "added_at": c.added_at,
                "adult": c.rating == ADULT,
            }
            for c in channels
        ]
        rows += [
            {
                "ref": o.ref,
                "name": o.name,
                "icon": o.logo,
                "category_id": ids[protocol.OWN_LIVE_CATEGORY],
                "epg_channel_id": o.epg_channel_id,
                "added_at": o.added_at,
                "adult": o.rating == ADULT,
            }
            for o in own
        ]
        if category_id is not None:
            rows = [r for r in rows if str(r["category_id"]) == category_id]
        return [protocol.live_stream(num=n, **row) for n, row in enumerate(rows, start=1)]

    # ── movies and series (the storefront's titles) ───────────────────────

    def vod_categories(self, who: XtreamPrincipal) -> list[dict[str, Any]]:
        return self._title_categories(who, TitleKind.MOVIE, "vod")

    def series_categories(self, who: XtreamPrincipal) -> list[dict[str, Any]]:
        return self._title_categories(who, TitleKind.SERIES, "series")

    def vod_streams(self, who: XtreamPrincipal, *, category_id: str | None = None) -> list[dict[str, Any]]:
        movies = self._title_list(who, TitleKind.MOVIE)
        ids = self.category_ids("vod", self._genre_names(movies, who.locale))
        out: list[dict[str, Any]] = []
        for movie in movies:
            cats = self._categories_of(movie, ids, who.locale)
            if category_id is not None and category_id not in {str(c) for c in cats}:
                continue
            out.append(
                protocol.vod_stream(
                    num=len(out) + 1,
                    ref=str(movie.play_ref),
                    name=movie.name,
                    icon=movie.poster_url,
                    category_id=cats[0],
                    category_ids=cats,
                    added_at=movie.added_at,
                    adult=movie.rating == ADULT,
                )
            )
        return out

    def vod_info(self, who: XtreamPrincipal, vod_id: str) -> dict[str, Any] | None:
        ref = protocol.content_ref(vod_id)
        if ref is None or self._titles is None:
            return None
        movie = self._titles.movie_by_ref(str(ref), kids_only=who.is_kids, locale=who.locale)
        if movie is None:
            return None
        ids = self.category_ids("vod", self._genre_names([movie], who.locale))
        cats = self._categories_of(movie, ids, who.locale)
        return protocol.vod_info(
            ref=str(movie.play_ref),
            name=movie.name,
            original_name=movie.name,
            plot=movie.synopsis,
            genres=list(movie.genres),
            year=movie.year,
            runtime_minutes=movie.runtime_minutes,
            poster=movie.poster_url,
            backdrop=movie.backdrop_url,
            category_id=cats[0],
            category_ids=cats,
            added_at=movie.added_at,
        )

    def series(self, who: XtreamPrincipal, *, category_id: str | None = None) -> list[dict[str, Any]]:
        shows = self._title_list(who, TitleKind.SERIES)
        ids = self.category_ids("series", self._genre_names(shows, who.locale))
        out: list[dict[str, Any]] = []
        for show in shows:
            cats = self._categories_of(show, ids, who.locale)
            if category_id is not None and category_id not in {str(c) for c in cats}:
                continue
            out.append(
                protocol.series_item(
                    num=len(out) + 1,
                    series_id=show.id,
                    name=show.name,
                    cover=show.poster_url,
                    backdrop=show.backdrop_url,
                    plot=show.synopsis,
                    genres=list(show.genres),
                    year=show.year,
                    runtime_minutes=show.runtime_minutes,
                    category_id=cats[0],
                    category_ids=cats,
                    added_at=show.added_at,
                    updated_at=show.updated_at,
                )
            )
        return out

    def series_info(self, who: XtreamPrincipal, series_id: str) -> dict[str, Any] | None:
        if self._titles is None or not series_id.isdigit() or len(series_id) > 18:
            return None
        show = self._titles.series(int(series_id), kids_only=who.is_kids, locale=who.locale)
        if show is None:
            return None
        ids = self.category_ids("series", self._genre_names([show], who.locale))
        cats = self._categories_of(show, ids, who.locale)
        episodes: dict[str, list[dict[str, Any]]] = {}
        for e in show.episodes:
            episodes.setdefault(str(e.season), []).append(
                protocol.episode(
                    ref=e.play_ref,
                    season=e.season,
                    number=e.number,
                    title=e.name,
                    plot=e.synopsis,
                    runtime_minutes=e.runtime_minutes,
                    still=e.still_url,
                    added_at=e.added_at,
                )
            )
        seasons = [
            protocol.season(
                int(number),
                name=protocol.word(who.locale, "season", n=number),
                episode_count=len(items),
                cover=show.poster_url,
            )
            for number, items in episodes.items()
        ]
        info = protocol.series_item(
            num=1,
            series_id=show.id,
            name=show.name,
            cover=show.poster_url,
            backdrop=show.backdrop_url,
            plot=show.synopsis,
            genres=list(show.genres),
            year=show.year,
            runtime_minutes=show.runtime_minutes,
            category_id=cats[0],
            category_ids=cats,
            added_at=show.added_at,
            updated_at=show.updated_at,
        )
        del info["num"]
        return {"seasons": seasons, "info": info, "episodes": episodes}

    def _title_list(self, who: XtreamPrincipal, kind: TitleKind) -> list[TitleListing]:
        if self._titles is None:
            return []
        return self._titles.listing(kind=kind, kids_only=who.is_kids, locale=who.locale)

    def _title_categories(self, who: XtreamPrincipal, kind: TitleKind, section: str) -> list[dict[str, Any]]:
        names = self._genre_names(self._title_list(who, kind), who.locale)
        ids = self.category_ids(section, names)
        return [protocol.category(ids[name], name) for name in names]

    @staticmethod
    def _genre_names(titles: list[TitleListing], locale: str) -> list[str]:
        names = sorted({g for t in titles for g in t.genres}, key=str.casefold)
        if any(not t.genres for t in titles):
            names.append(protocol.word(locale, "other"))
        return names

    @staticmethod
    def _categories_of(title: TitleListing, ids: dict[str, int], locale: str) -> list[int]:
        names = list(title.genres) or [protocol.word(locale, "other")]
        return [ids[n] for n in names]

    # ── categories ────────────────────────────────────────────────────────

    def category_ids(self, section: str, names: list[str]) -> dict[str, int]:
        """Stable numeric id per name, created the first time a name is listed."""
        if not names:
            return {}
        table = XtreamCategory.__table__
        with self._uow() as uow:
            known = self._known(uow.session, section, names)
            missing = [n for n in dict.fromkeys(names) if n not in known]
            if missing:
                uow.session.execute(
                    dialect_insert(uow.session, table)
                    .values([{"section": section, "name": n} for n in missing])
                    .on_conflict_do_nothing(index_elements=["section", "name"])  # a parallel request won the race
                )
                known = self._known(uow.session, section, names)
            return known

    @staticmethod
    def _known(session: Any, section: str, names: list[str]) -> dict[str, int]:
        rows = session.execute(
            select(XtreamCategory.name, XtreamCategory.id).where(
                XtreamCategory.section == section, XtreamCategory.name.in_(names)
            )
        )
        return {name: int(cid) for name, cid in rows}

    def _live_category_names(self, who: XtreamPrincipal, *, channels: Any = None, own: Any = None) -> list[str]:
        if channels is None:
            channels = self._catalog.listing(kind="live", kids_only=who.is_kids)
        if own is None:
            own = self._live.listing(kids_only=who.is_kids) if self._live is not None else []
        names = list(dict.fromkeys(c.group for c in channels))
        if own:
            names.append(protocol.OWN_LIVE_CATEGORY)
        return names
