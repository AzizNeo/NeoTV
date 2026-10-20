"""What an Xtream app lists: other modules' catalogues mapped to the protocol's shapes.

Read through capabilities only (``catalog.read``, optional ``live.read`` and ``titles.read``), with
the profile's kids filter applied by the owning module — the same rule as the web storefront.
Movies and series are the storefront's titles (curated, with artwork and synopses) in the
account's language; their categories are the titles' genres.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select

from app.kernel.db import dialect_insert
from app.kernel.uow import UnitOfWorkFactory
from app.modules.catalog.api import CatalogReader
from app.modules.live.api import LiveListing, LiveReader, ProgramListing
from app.modules.titles.api import TitleCatalogReader, TitleKind, TitleListing
from app.modules.xtream import protocol
from app.modules.xtream.domain import XtreamPrincipal
from app.modules.xtream.models import XtreamCategory

ADULT = "adult"
#: The guide window apps get: what just ended (for "catch up on what I missed" screens) to days ahead.
GUIDE_BEHIND = timedelta(hours=6)
GUIDE_AHEAD = timedelta(days=3)


class _Entitlements(Protocol):  # consumer-owned port for the optional billing capability
    def for_user(self, user_id: int) -> Any: ...


class XtreamCatalog:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        catalog: CatalogReader,
        live: LiveReader | None,
        titles: TitleCatalogReader | None,
        entitlements: _Entitlements | None = None,
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._live = live
        self._titles = titles
        self._entitlements = entitlements

    def catchup_days(self, who: XtreamPrincipal, channel_days: int) -> int:
        """How far back this account may watch a channel: min(channel archive, plan window).
        The same rule as the playback gate's catch-up policy, which has the last word."""
        if channel_days <= 0:
            return 0
        if self._entitlements is None:
            return channel_days
        return max(0, min(channel_days, int(getattr(self._entitlements.for_user(who.user_id), "catchup_days", 0))))

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
                "epg_channel_id": o.epg_channel_id or protocol.own_epg_id(o.ref),
                "added_at": o.added_at,
                "adult": o.rating == ADULT,
                "archive_days": self.catchup_days(who, o.catchup_days),
            }
            for o in own
        ]
        if category_id is not None:
            rows = [r for r in rows if str(r["category_id"]) == category_id]
        return [protocol.live_stream(num=n, **row) for n, row in enumerate(rows, start=1)]

    # ── guide (only NeoTV's own live channels have one) ───────────────────

    def short_epg(self, who: XtreamPrincipal, stream: str, *, limit: int, now: datetime) -> dict[str, Any]:
        channel = self._own_channel(who, stream)
        if channel is None:
            return {"epg_listings": []}
        programmes = [p for p in self._programmes([channel], now, now + GUIDE_AHEAD) if p.ends_at > now][:limit]
        return {"epg_listings": [self._listing(channel, p) for p in programmes]}

    def simple_data_table(self, who: XtreamPrincipal, stream: str, *, now: datetime) -> dict[str, Any]:
        channel = self._own_channel(who, stream)
        if channel is None:
            return {"epg_listings": []}
        days = self.catchup_days(who, channel.catchup_days)
        since = now - timedelta(days=days) if days else None
        # An archived channel's table reaches back as far as the account can watch (apps list it).
        programmes = self._programmes([channel], min(since or now, now - GUIDE_BEHIND), now + GUIDE_AHEAD)
        return {"epg_listings": [self._listing(channel, p, now=now, archived_since=since) for p in programmes]}

    def guide(self, who: XtreamPrincipal, *, now: datetime) -> bytes:
        own = self._live.listing(kids_only=who.is_kids) if self._live is not None else []
        back = max([GUIDE_BEHIND, *(timedelta(days=self.catchup_days(who, c.catchup_days)) for c in own)])
        by_id = {c.id: c for c in own}
        channels = [protocol.GuideChannel(epg_id=self._epg_id(c), name=c.name, icon=c.logo) for c in own]
        programmes = [
            protocol.GuideProgramme(
                epg_id=self._epg_id(by_id[p.channel_id]),
                title=p.title,
                description=p.description,
                starts_at=p.starts_at,
                ends_at=p.ends_at,
            )
            for p in self._programmes(own, now - back, now + GUIDE_AHEAD)
        ]
        return protocol.xmltv(channels, programmes, language=who.locale)

    def _own_channel(self, who: XtreamPrincipal, stream: str) -> LiveListing | None:
        ref = protocol.content_ref(stream)
        if ref is None or ref.namespace != "live" or self._live is None:
            return None
        return next((c for c in self._live.listing(kids_only=who.is_kids) if c.id == ref.id), None)

    def _programmes(self, channels: list[LiveListing], start: datetime, end: datetime) -> list[ProgramListing]:
        if self._live is None or not channels:
            return []
        return self._live.programmes(channel_ids=[c.id for c in channels], start=start, end=end)

    @staticmethod
    def _epg_id(channel: LiveListing) -> str:
        return channel.epg_channel_id or protocol.own_epg_id(channel.ref)

    def _listing(
        self,
        channel: LiveListing,
        p: ProgramListing,
        *,
        now: datetime | None = None,
        archived_since: datetime | None = None,
    ) -> dict[str, Any]:
        return protocol.epg_listing(
            program_id=p.id,
            epg_id=self._epg_id(channel),
            ref=channel.ref,
            title=p.title,
            description=p.description,
            starts_at=p.starts_at,
            ends_at=p.ends_at,
            now=now,
            archived_since=archived_since,
        )

    # ── M3U playlist ──────────────────────────────────────────────────────

    def playlist(self, who: XtreamPrincipal) -> list[protocol.PlaylistEntry]:
        """Everything the credential can play: live channels, movies, then series episode by episode."""
        entries = [
            protocol.PlaylistEntry("live", c.ref, c.name, c.group, c.logo)
            for c in self._catalog.listing(kind="live", kids_only=who.is_kids)
        ]
        own = self._live.listing(kids_only=who.is_kids) if self._live is not None else []
        entries += [
            protocol.PlaylistEntry(
                "live",
                c.ref,
                c.name,
                protocol.OWN_LIVE_CATEGORY,
                c.logo,
                self._epg_id(c),
                catchup_days=self.catchup_days(who, c.catchup_days),
            )
            for c in own
        ]
        other = protocol.word(who.locale, "other")
        for movie in self._title_list(who, TitleKind.MOVIE):
            group = movie.genres[0] if movie.genres else other
            entries.append(protocol.PlaylistEntry("movie", str(movie.play_ref), movie.name, group, movie.poster_url))
        for show in self._series_with_episodes(who):
            entries += [
                protocol.PlaylistEntry(
                    "series", e.play_ref, f"{show.name} S{e.season:02d}E{e.number:02d}", show.name, show.poster_url
                )
                for e in show.episodes
            ]
        return entries

    def _series_with_episodes(self, who: XtreamPrincipal) -> list[TitleListing]:
        if self._titles is None:
            return []
        shows = (
            self._titles.series(listed.id, kids_only=who.is_kids, locale=who.locale)
            for listed in self._title_list(who, TitleKind.SERIES)
        )
        return [show for show in shows if show is not None]

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
