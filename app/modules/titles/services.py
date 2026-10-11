"""Use cases of the titles module.

Availability is computed at read time with one batched ``playback.content`` lookup
per page (never stored), so titles follow their sources: a removed channel makes a
title unavailable, a returning one makes it playable again.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.playback.api import ContentDirectory, ContentKind
from app.modules.titles.domain import (
    EpisodeDraft,
    InvalidTitleError,
    PlaySourceNotFoundError,
    RatingConflictError,
    SeasonDraft,
    TitleDraft,
    TitleKind,
    TitleNotFoundError,
    slugify,
    validate,
)
from app.modules.titles.models import Episode, Genre, Season, Title
from app.shared_kernel.ratings import KIDS_ALLOWED


# ── Read models ─────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class TitleAdminRow:
    slug: str
    kind: str
    name: str
    year: int | None
    is_published: bool
    featured_rank: int | None
    sources: int
    unavailable_sources: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TitleAdminPage:
    items: list[TitleAdminRow]
    next_cursor: str | None


# ── Repository ──────────────────────────────────────────────────────────────
class TitleRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def by_slug(self, slug: str) -> Title | None:
        return self._s.execute(select(Title).where(Title.slug == slug)).scalar_one_or_none()

    def genres_for(self, names: Iterable[str]) -> list[Genre]:
        """Get-or-create by slug; the first spelling of a genre becomes its display name."""
        wanted = {slugify(n): " ".join(n.split()) for n in names}
        existing = {g.slug: g for g in self._s.execute(select(Genre).where(Genre.slug.in_(wanted))).scalars()}
        for slug, name in wanted.items():
            if slug not in existing:
                existing[slug] = Genre(slug=slug, name=name[:80])
                self._s.add(existing[slug])
        return [existing[s] for s in wanted]

    def admin_page(self, *, search: str | None, after: str | None, limit: int) -> list[Title]:
        stmt = select(Title)
        if search:
            stmt = stmt.where(func.lower(Title.name).like(f"%{search.strip().lower()}%"))
        if after:
            stmt = stmt.where(Title.slug > after)
        return list(self._s.execute(stmt.order_by(Title.slug).limit(limit)).scalars())


def title_refs(title: Title) -> list[str]:
    refs = [title.play_ref] if title.play_ref else []
    refs += [e.play_ref for s in title.seasons for e in s.episodes if e.play_ref]
    return refs


# ── Admin use cases ─────────────────────────────────────────────────────────
class TitleAdminService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock, content: ContentDirectory) -> None:
        self._uow = uow
        self._clock = clock
        self._content = content

    def upsert(self, draft: TitleDraft) -> bool:
        """Replace the whole aggregate identified by ``draft.slug``. Returns ``True`` if it was created."""
        validate(draft)
        self._check_sources(draft)
        with self._uow() as uow:
            repo = TitleRepository(uow.session)
            title = repo.by_slug(draft.slug)
            created = title is None
            if title is None:
                title = Title(slug=draft.slug, created_at=self._clock.now())
                uow.session.add(title)
            title.kind = str(draft.kind)
            title.name = draft.name.strip()
            title.synopsis = draft.synopsis
            title.year = draft.year
            title.runtime_minutes = draft.runtime_minutes
            title.rating = draft.rating
            title.poster_url = draft.poster_url
            title.backdrop_url = draft.backdrop_url
            title.play_ref = draft.play_ref
            title.featured_rank = draft.featured_rank
            title.is_published = draft.is_published
            title.updated_at = self._clock.now()
            title.genres = repo.genres_for(draft.genres)
            title.seasons.clear()
            uow.session.flush()  # delete old children first: (title_id, number) is unique
            title.seasons.extend(
                Season(
                    number=s.number,
                    name=s.name,
                    episodes=[
                        Episode(
                            number=e.number,
                            name=e.name.strip(),
                            synopsis=e.synopsis,
                            runtime_minutes=e.runtime_minutes,
                            still_url=e.still_url,
                            play_ref=e.play_ref,
                        )
                        for e in s.episodes
                    ],
                )
                for s in draft.seasons
            )
        return created

    def document(self, slug: str) -> TitleDraft:
        """The editable document (what ``upsert`` accepts) — round-trips losslessly."""
        with self._uow() as uow:
            title = self._get(uow.session, slug)
            return to_draft(title)

    def delete(self, slug: str) -> None:
        with self._uow() as uow:
            uow.session.delete(self._get(uow.session, slug))

    def page(self, *, search: str | None, after: str | None, limit: int) -> TitleAdminPage:
        limit = max(1, min(limit, 100))
        with self._uow() as uow:
            rows = TitleRepository(uow.session).admin_page(search=search, after=after, limit=limit + 1)
            has_next = len(rows) > limit
            rows = rows[:limit]
            refs = {t.slug: title_refs(t) for t in rows}
        alive = self._content.cards(sorted({r for rs in refs.values() for r in rs}))
        items = [
            TitleAdminRow(
                slug=t.slug,
                kind=t.kind,
                name=t.name,
                year=t.year,
                is_published=bool(t.is_published),
                featured_rank=t.featured_rank,
                sources=len(refs[t.slug]),
                unavailable_sources=sum(1 for r in refs[t.slug] if r not in alive),
                updated_at=t.updated_at,
            )
            for t in rows
        ]
        return TitleAdminPage(items=items, next_cursor=rows[-1].slug if has_next and rows else None)

    # ── internals ──────────────────────────────────────────────────────────
    def _check_sources(self, draft: TitleDraft) -> None:
        refs = sorted(draft.play_refs())
        cards = self._content.cards(refs) if refs else {}
        missing = [r for r in refs if r not in cards]
        if missing:
            raise PlaySourceNotFoundError("Some play sources do not exist", details=missing)
        live = [r for r in refs if cards[r].kind is not ContentKind.VOD]
        if live:
            raise InvalidTitleError(
                "Title document is invalid", details=[f"play_ref {r!r}: not on demand" for r in live]
            )
        if draft.rating in KIDS_ALLOWED:
            stricter = {r: str(cards[r].rating) for r in refs if cards[r].rating not in KIDS_ALLOWED}
            if stricter:
                # A kids profile must be able to play exactly what it can see.
                raise RatingConflictError(
                    f"Title is rated {draft.rating!r} but kids may not play some of its sources",
                    source_ratings=stricter,
                )

    @staticmethod
    def _get(session: Session, slug: str) -> Title:
        title = TitleRepository(session).by_slug(slug)
        if title is None:
            raise TitleNotFoundError("Title not found")
        return title


def to_draft(title: Title) -> TitleDraft:
    return TitleDraft(
        slug=title.slug,
        kind=TitleKind(title.kind),
        name=title.name,
        rating=title.rating,
        synopsis=title.synopsis,
        year=title.year,
        runtime_minutes=title.runtime_minutes,
        poster_url=title.poster_url,
        backdrop_url=title.backdrop_url,
        play_ref=title.play_ref,
        genres=tuple(g.name for g in title.genres),
        featured_rank=title.featured_rank,
        is_published=bool(title.is_published),
        seasons=tuple(
            SeasonDraft(
                number=s.number,
                name=s.name,
                episodes=tuple(
                    EpisodeDraft(
                        number=e.number,
                        name=e.name,
                        play_ref=e.play_ref,
                        synopsis=e.synopsis,
                        runtime_minutes=e.runtime_minutes,
                        still_url=e.still_url,
                    )
                    for e in s.episodes
                ),
            )
            for s in title.seasons
        ),
    )
