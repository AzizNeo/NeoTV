"""Viewer-facing reads of the titles module (the write side lives in ``services.py``).

Visibility: only published titles; a kids profile sees only ratings in
``KIDS_ALLOWED`` (enforced on write to match every source, see services).
Availability: computed per response with *one* batched ``playback.content``
lookup — listings flag unplayable titles (``available=False``) instead of hiding
them, the hero shows only playable ones.
Language: every read takes the viewer's ``locale``; names, synopses, episode and genre
names come from its translation when there is one, else from the original. Search
matches the original and every translation; "A–Z" sorts by the name the viewer sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.orm import Session

from app.kernel.uow import UnitOfWorkFactory
from app.modules.playback.api import ContentDirectory
from app.modules.titles.domain import TitleKind, TitleNotFoundError
from app.modules.titles.models import Episode, Genre, GenreText, Title, TitleText, title_genres
from app.modules.titles.services import title_refs
from app.shared_kernel.locale import DEFAULT_LOCALE
from app.shared_kernel.ratings import KIDS_ALLOWED

Sort = Literal["recent", "name", "year"]


# ── Read models ─────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class TitleCard:
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


@dataclass(frozen=True, slots=True)
class TitlePage:
    items: list[TitleCard]
    total: int
    page: int
    per_page: int


@dataclass(frozen=True, slots=True)
class FeaturedTitle:
    card: TitleCard
    synopsis: str | None
    play_ref: str | None  # movie: its source; series: the first available episode


@dataclass(frozen=True, slots=True)
class EpisodeView:
    number: int
    name: str
    synopsis: str | None
    runtime_minutes: int | None
    still_url: str | None
    play_ref: str | None
    available: bool


@dataclass(frozen=True, slots=True)
class SeasonView:
    number: int
    name: str | None
    episodes: list[EpisodeView]


@dataclass(frozen=True, slots=True)
class GenreLink:
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class TitleDetail:
    card: TitleCard
    synopsis: str | None
    play_ref: str | None
    seasons: list[SeasonView]
    genre_links: list[GenreLink]  # card.genres are display names; these also carry the browse filter slug


@dataclass(frozen=True, slots=True)
class GenreCount:
    slug: str
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class Rail:
    genre: GenreCount
    items: list[TitleCard]


@dataclass(frozen=True, slots=True)
class TitleQuery:
    kids_only: bool
    locale: str = DEFAULT_LOCALE
    kind: TitleKind | None = None
    genre: str | None = None
    search: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    sort: Sort = "recent"
    page: int = 1
    per_page: int = 24


# ── Service ─────────────────────────────────────────────────────────────────
class TitleQueryService:
    def __init__(self, uow: UnitOfWorkFactory, content: ContentDirectory) -> None:
        self._uow = uow
        self._content = content

    def page(self, q: TitleQuery) -> TitlePage:
        with self._uow() as uow:
            stmt = _filtered(_visible(q.kids_only), q)
            total = int(uow.session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
            rows = list(
                uow.session.execute(
                    stmt.order_by(*_order(q.sort, q.locale), Title.id)
                    .offset((q.page - 1) * q.per_page)
                    .limit(q.per_page)
                ).scalars()
            )
            cards = self._cards(rows, q.locale)
        return TitlePage(items=cards, total=total, page=q.page, per_page=q.per_page)

    def genres(self, *, kids_only: bool, locale: str = DEFAULT_LOCALE) -> list[GenreCount]:
        with self._uow() as uow:
            return _genre_counts(uow.session, kids_only, locale)

    def rails(self, *, kids_only: bool, genres: int, per_rail: int, locale: str = DEFAULT_LOCALE) -> list[Rail]:
        """Home rows: the biggest genres, each with its titles (featured first, then newest)."""
        with self._uow() as uow:
            rails: list[tuple[GenreCount, list[Title]]] = []
            for genre in _genre_counts(uow.session, kids_only, locale)[:genres]:
                stmt = _filtered(_visible(kids_only), TitleQuery(kids_only=kids_only, genre=genre.slug))
                rows = uow.session.execute(
                    stmt.order_by(*_order("featured", locale), Title.id).limit(per_rail)
                ).scalars()
                rails.append((genre, list(rows)))
            alive = self._alive([t for _, rows in rails for t in rows])
            return [Rail(genre=g, items=[_card(t, alive, locale) for t in rows]) for g, rows in rails]

    def featured(self, *, kids_only: bool, limit: int, locale: str = DEFAULT_LOCALE) -> list[FeaturedTitle]:
        with self._uow() as uow:
            rows = list(
                uow.session.execute(
                    _visible(kids_only)
                    .where(Title.featured_rank.is_not(None))
                    .order_by(Title.featured_rank, Title.id)
                    .limit(limit * 2)  # head-room: unplayable ones are dropped below
                ).scalars()
            )
            alive = self._alive(rows)
            out = []
            for t in rows:
                card = _card(t, alive, locale)
                if card.available:
                    synopsis = _text(t, locale)[1]
                    out.append(FeaturedTitle(card=card, synopsis=synopsis, play_ref=_first_playable(t, alive)))
            return out[:limit]

    def detail(self, slug: str, *, kids_only: bool, locale: str = DEFAULT_LOCALE) -> TitleDetail:
        with self._uow() as uow:
            title = uow.session.execute(_visible(kids_only).where(Title.slug == slug)).scalar_one_or_none()
            if title is None:
                raise TitleNotFoundError("Title not found")  # also for hidden ones: no existence oracle
            alive = self._alive([title])
            return TitleDetail(
                card=_card(title, alive, locale),
                synopsis=_text(title, locale)[1],
                play_ref=title.play_ref,
                seasons=[
                    SeasonView(
                        number=s.number,
                        name=s.name,
                        episodes=[
                            EpisodeView(
                                number=e.number,
                                name=_text(e, locale)[0],
                                synopsis=_text(e, locale)[1],
                                runtime_minutes=e.runtime_minutes,
                                still_url=e.still_url,
                                play_ref=e.play_ref,
                                available=e.play_ref in alive,
                            )
                            for e in s.episodes
                        ],
                    )
                    for s in title.seasons
                ],
                genre_links=[GenreLink(slug=g.slug, name=_genre_name(g, locale)) for g in title.genres],
            )

    # ── internals ──────────────────────────────────────────────────────────
    def _alive(self, titles: list[Title]) -> set[str]:
        refs = sorted({r for t in titles for r in title_refs(t)})
        return set(self._content.cards(refs)) if refs else set()

    def _cards(self, titles: list[Title], locale: str) -> list[TitleCard]:
        alive = self._alive(titles)
        return [_card(t, alive, locale) for t in titles]


# ── Query building blocks ───────────────────────────────────────────────────
def _seen_name(locale: str) -> ColumnElement[str]:
    """The name a viewer in ``locale`` sees: its translation, else the original."""
    translated = (
        select(TitleText.name).where(TitleText.title_id == Title.id, TitleText.locale == locale).scalar_subquery()
    )
    return func.coalesce(translated, Title.name)


def _order(sort: str, locale: str) -> tuple[ColumnElement[object], ...]:
    name = _seen_name(locale) if locale != DEFAULT_LOCALE else Title.name
    return {
        "recent": (Title.created_at.desc(),),
        "name": (name,),
        "year": (Title.year.desc().nulls_last(), name),
        "featured": (Title.featured_rank.asc().nulls_last(), Title.year.desc().nulls_last(), name),
    }[sort]


def _visible(kids_only: bool) -> Select[tuple[Title]]:
    stmt = select(Title).where(Title.is_published.is_(True))
    return stmt.where(Title.rating.in_(sorted(KIDS_ALLOWED))) if kids_only else stmt


def _filtered(stmt: Select[tuple[Title]], q: TitleQuery) -> Select[tuple[Title]]:
    if q.kind is not None:
        stmt = stmt.where(Title.kind == str(q.kind))
    if q.genre:
        stmt = stmt.where(
            Title.id.in_(
                select(title_genres.c.title_id)
                .join(Genre, Genre.id == title_genres.c.genre_id)
                .where(Genre.slug == q.genre)
            )
        )
    if q.search:
        needle = f"%{_escape_like(q.search.strip().lower())}%"
        translated = select(TitleText.title_id).where(func.lower(TitleText.name).like(needle, escape="\\"))
        stmt = stmt.where(or_(func.lower(Title.name).like(needle, escape="\\"), Title.id.in_(translated)))
    if q.year_from is not None:
        stmt = stmt.where(Title.year >= q.year_from)
    if q.year_to is not None:
        stmt = stmt.where(Title.year <= q.year_to)
    return stmt


def _genre_counts(session: Session, kids_only: bool, locale: str) -> list[GenreCount]:
    visible = _visible(kids_only).with_only_columns(Title.id).subquery()
    translated = (
        select(GenreText.name).where(GenreText.genre_id == Genre.id, GenreText.locale == locale).scalar_subquery()
    )
    name = func.coalesce(translated, Genre.name)
    stmt = (
        select(Genre.slug, name, func.count(title_genres.c.title_id))
        .join(title_genres, title_genres.c.genre_id == Genre.id)
        .where(title_genres.c.title_id.in_(select(visible.c.id)))
        .group_by(Genre.id, Genre.slug, Genre.name)
        .order_by(func.count(title_genres.c.title_id).desc(), name)
    )
    return [GenreCount(slug=s, name=n, count=int(c)) for s, n, c in session.execute(stmt)]


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _text(owner: Title | Episode, locale: str) -> tuple[str, str | None]:
    """(name, synopsis) in ``locale``; a translation without a synopsis keeps the original's."""
    for text in owner.texts:
        if text.locale == locale:
            return text.name, text.synopsis if text.synopsis is not None else owner.synopsis
    return owner.name, owner.synopsis


def _genre_name(genre: Genre, locale: str) -> str:
    return next((t.name for t in genre.texts if t.locale == locale), genre.name)


def _card(t: Title, alive: set[str], locale: str) -> TitleCard:
    return TitleCard(
        slug=t.slug,
        kind=t.kind,
        name=_text(t, locale)[0],
        year=t.year,
        rating=t.rating,
        runtime_minutes=t.runtime_minutes,
        season_count=len(t.seasons),
        genres=[_genre_name(g, locale) for g in t.genres],
        poster_url=t.poster_url,
        backdrop_url=t.backdrop_url,
        available=_first_playable(t, alive) is not None,
    )


def _first_playable(t: Title, alive: set[str]) -> str | None:
    if t.kind == TitleKind.MOVIE:
        return t.play_ref if t.play_ref in alive else None
    return next((e.play_ref for s in t.seasons for e in s.episodes if e.play_ref in alive), None)
