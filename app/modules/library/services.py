"""Library application services (profile-scoped).

* Every query is keyed by ``profile_id`` from the verified profile context —
  one profile can never read or write another profile's library.
* Content is hydrated through the ``playback.content`` capability (namespace
  agnostic). Rows whose content no longer resolves (removed, or its module
  disabled) are skipped in responses and purged by the ``ContentRemoved``
  consumer.
* Kids profiles only ever see items the shared rating rule allows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.kernel.db import dialect_insert
from app.kernel.http.profile_context import ProfileContext
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.library.models import Favorite, HistoryEntry, Progress
from app.modules.playback.api import ContentCard, ContentDirectory
from app.shared_kernel.content import ContentRef
from app.shared_kernel.events import PlaybackSessionEnded
from app.shared_kernel.ratings import allowed_for_kids

COMPLETED_RATIO = 0.90
CONTINUE_MIN_RATIO = 0.05
MAX_FAVORITES_PER_PROFILE = 1000
MIN_HISTORY_SECONDS = 10
HISTORY_RETENTION_DAYS = 365


class LibraryContentNotFoundError(LookupError):
    pass


class FavoriteLimitReachedError(Exception):
    pass


# ── Views ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CardView:
    ref: str
    title: str
    image: str | None
    group: str | None
    kind: str
    rating: str

    @classmethod
    def of(cls, card: ContentCard) -> CardView:
        return cls(card.ref, card.title, card.image, card.group, str(card.kind), str(card.rating))


@dataclass(frozen=True, slots=True)
class FavoriteItem:
    content: CardView
    added_at: datetime


@dataclass(frozen=True, slots=True)
class ProgressView:
    content_ref: str
    has_progress: bool
    position_s: int
    duration_s: int
    progress_percent: int
    completed: bool
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ContinueItem:
    content: CardView
    position_s: int
    duration_s: int
    progress_percent: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class HistoryItem:
    id: int
    content: CardView
    watched_at: datetime
    watched_seconds: int


def _ratio(position_s: int, duration_s: int) -> float:
    return 0.0 if duration_s <= 0 else max(0.0, min(position_s / duration_s, 1.0))


class LibraryService:
    def __init__(self, uow: UnitOfWorkFactory, content: ContentDirectory, clock: Clock) -> None:
        self._uow = uow
        self._content = content
        self._clock = clock

    # ── favourites ────────────────────────────────────────────────────────
    def favorites(self, ctx: ProfileContext, *, limit: int, offset: int) -> list[FavoriteItem]:
        with self._uow() as uow:
            rows = uow.session.execute(
                select(Favorite.content_ref, Favorite.created_at)
                .where(Favorite.profile_id == ctx.profile_id)
                .order_by(Favorite.created_at.desc(), Favorite.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        cards = self._cards(ctx, [r.content_ref for r in rows])
        return [FavoriteItem(cards[r.content_ref], r.created_at) for r in rows if r.content_ref in cards]

    def favorite_refs(self, profile_id: int, limit: int = MAX_FAVORITES_PER_PROFILE) -> list[str]:
        with self._uow() as uow:
            return list(
                uow.session.execute(
                    select(Favorite.content_ref)
                    .where(Favorite.profile_id == profile_id)
                    .order_by(Favorite.created_at.desc())
                    .limit(limit)
                ).scalars()
            )

    def add_favorite(self, ctx: ProfileContext, content_ref: str) -> FavoriteItem:
        """Idempotent (PUT semantics): adding twice is not an error."""
        ref = self._existing(ctx, content_ref)
        now = self._clock.now()
        with self._uow() as uow:
            count = uow.session.execute(
                select(func.count(Favorite.id)).where(Favorite.profile_id == ctx.profile_id)
            ).scalar_one()
            if count >= MAX_FAVORITES_PER_PROFILE:
                exists = uow.session.execute(
                    select(Favorite.id).where(Favorite.profile_id == ctx.profile_id, Favorite.content_ref == ref)
                ).first()
                if not exists:
                    raise FavoriteLimitReachedError(
                        f"a profile can keep at most {MAX_FAVORITES_PER_PROFILE} favourites"
                    )
            uow.session.execute(
                dialect_insert(uow.session, Favorite.__table__)
                .values(user_id=ctx.user_id, profile_id=ctx.profile_id, content_ref=ref, created_at=now)
                .on_conflict_do_nothing(index_elements=["profile_id", "content_ref"])
            )
            added_at = uow.session.execute(
                select(Favorite.created_at).where(Favorite.profile_id == ctx.profile_id, Favorite.content_ref == ref)
            ).scalar_one()
        card = self._cards(ctx, [ref])[ref]
        return FavoriteItem(card, added_at)

    def remove_favorite(self, ctx: ProfileContext, content_ref: str) -> None:
        ref = str(ContentRef.parse(content_ref))
        with self._uow() as uow:
            uow.session.execute(
                delete(Favorite).where(Favorite.profile_id == ctx.profile_id, Favorite.content_ref == ref)
            )

    # ── progress / continue watching ──────────────────────────────────────
    def save_progress(self, ctx: ProfileContext, content_ref: str, *, position_s: int, duration_s: int) -> ProgressView:
        ref = str(ContentRef.parse(content_ref))
        position_s = max(0, position_s if duration_s <= 0 else min(position_s, duration_s))
        ratio = _ratio(position_s, duration_s)
        completed = ratio >= COMPLETED_RATIO
        now = self._clock.now()
        values = {
            "position_s": position_s,
            "duration_s": max(0, duration_s),
            "ratio": ratio,
            "completed": completed,
            "updated_at": now,
        }
        with self._uow() as uow:
            # Hot path (every few seconds while playing): plain UPDATE first;
            # the content is validated only when a new row is created.
            updated = uow.session.execute(
                update(Progress)
                .where(Progress.profile_id == ctx.profile_id, Progress.content_ref == ref)
                .values(**values)
            ).rowcount
            if not updated:
                self._existing(ctx, ref)
                uow.session.execute(
                    dialect_insert(uow.session, Progress.__table__)
                    .values(user_id=ctx.user_id, profile_id=ctx.profile_id, content_ref=ref, created_at=now, **values)
                    .on_conflict_do_update(index_elements=["profile_id", "content_ref"], set_=values)
                )
        return ProgressView(ref, True, position_s, max(0, duration_s), round(ratio * 100), completed, now)

    def progress(self, ctx: ProfileContext, content_ref: str) -> ProgressView:
        ref = str(ContentRef.parse(content_ref))
        with self._uow() as uow:
            row = uow.session.execute(
                select(Progress).where(Progress.profile_id == ctx.profile_id, Progress.content_ref == ref)
            ).scalar_one_or_none()
            if row is None:
                return ProgressView(ref, False, 0, 0, 0, False, None)
            return ProgressView(
                ref, True, row.position_s, row.duration_s, round(row.ratio * 100), bool(row.completed), row.updated_at
            )

    def clear_progress(self, ctx: ProfileContext, content_ref: str) -> None:
        ref = str(ContentRef.parse(content_ref))
        with self._uow() as uow:
            uow.session.execute(
                delete(Progress).where(Progress.profile_id == ctx.profile_id, Progress.content_ref == ref)
            )

    def continue_watching(self, ctx: ProfileContext, *, limit: int) -> list[ContinueItem]:
        with self._uow() as uow:
            rows = list(
                uow.session.execute(
                    select(Progress)
                    .where(
                        Progress.profile_id == ctx.profile_id,
                        Progress.completed.is_(False),
                        Progress.ratio >= CONTINUE_MIN_RATIO,
                        Progress.ratio < COMPLETED_RATIO,
                    )
                    .order_by(Progress.updated_at.desc())
                    .limit(limit)
                ).scalars()
            )
            snapshot = [(r.content_ref, r.position_s, r.duration_s, r.ratio, r.updated_at) for r in rows]
        cards = self._cards(ctx, [s[0] for s in snapshot])
        return [
            ContinueItem(cards[ref], pos, dur, round(ratio * 100), at)
            for ref, pos, dur, ratio, at in snapshot
            if ref in cards
        ]

    # ── history ───────────────────────────────────────────────────────────
    def history(self, ctx: ProfileContext, *, limit: int, before_id: int | None) -> list[HistoryItem]:
        with self._uow() as uow:
            stmt = (
                select(HistoryEntry.id, HistoryEntry.content_ref, HistoryEntry.watched_at, HistoryEntry.watched_seconds)
                .where(HistoryEntry.profile_id == ctx.profile_id)
                .order_by(HistoryEntry.id.desc())
                .limit(limit)
            )
            if before_id:
                stmt = stmt.where(HistoryEntry.id < before_id)
            rows = uow.session.execute(stmt).all()
        cards = self._cards(ctx, [r.content_ref for r in rows])
        return [
            HistoryItem(r.id, cards[r.content_ref], r.watched_at, r.watched_seconds)
            for r in rows
            if r.content_ref in cards
        ]

    def recent(self, ctx: ProfileContext, *, limit: int) -> list[CardView]:
        refs = self.recent_refs(ctx.profile_id, limit)
        cards = self._cards(ctx, refs)
        return [cards[ref] for ref in refs if ref in cards]

    def recent_refs(self, profile_id: int, limit: int = 50) -> list[str]:
        """Distinct content, most recently watched first."""
        with self._uow() as uow:
            last = func.max(HistoryEntry.watched_at).label("last")
            return [
                row.content_ref
                for row in uow.session.execute(
                    select(HistoryEntry.content_ref, last)
                    .where(HistoryEntry.profile_id == profile_id)
                    .group_by(HistoryEntry.content_ref)
                    .order_by(last.desc())
                    .limit(limit)
                ).all()
            ]

    def clear_history(self, ctx: ProfileContext) -> int:
        with self._uow() as uow:
            return int(
                uow.session.execute(delete(HistoryEntry).where(HistoryEntry.profile_id == ctx.profile_id)).rowcount or 0
            )

    # ── event consumers (inside the consumer's UoW) ───────────────────────
    def record_session(self, session: Session, event: PlaybackSessionEnded) -> bool:
        if event.watched_seconds < MIN_HISTORY_SECONDS:
            return False
        result = session.execute(
            dialect_insert(session, HistoryEntry.__table__)
            .values(
                user_id=event.user_id,
                profile_id=event.profile_id,
                content_ref=event.content_ref,
                session_token=event.session_token,
                watched_seconds=event.watched_seconds,
                watched_at=datetime.fromisoformat(event.ended_at),
            )
            .on_conflict_do_nothing(index_elements=["session_token"])
            .returning(HistoryEntry.__table__.c.id)
        )
        return result.first() is not None

    @staticmethod
    def purge_content(session: Session, content_ref: str) -> None:
        for model in (Favorite, Progress, HistoryEntry):
            session.execute(delete(model).where(model.content_ref == content_ref))

    @staticmethod
    def purge_profile(session: Session, profile_id: int) -> None:
        for model in (Favorite, Progress, HistoryEntry):
            session.execute(delete(model).where(model.profile_id == profile_id))

    def purge_old_history(self, retention_days: int = HISTORY_RETENTION_DAYS) -> int:
        cutoff = self._clock.now() - timedelta(days=retention_days)
        with self._uow() as uow:
            return int(uow.session.execute(delete(HistoryEntry).where(HistoryEntry.watched_at < cutoff)).rowcount or 0)

    # ── helpers ───────────────────────────────────────────────────────────
    def _existing(self, ctx: ProfileContext, content_ref: str) -> str:
        ref = ContentRef.parse(content_ref)
        descriptor = self._content.describe(ref)
        if descriptor is None or (ctx.is_kids and not allowed_for_kids(str(descriptor.rating))):
            raise LibraryContentNotFoundError(f"content '{ref}' not found")
        return str(ref)

    def _cards(self, ctx: ProfileContext, refs: list[str]) -> dict[str, CardView]:
        if not refs:
            return {}
        cards = self._content.cards(list(dict.fromkeys(refs)))
        return {
            ref: CardView.of(card)
            for ref, card in cards.items()
            if not ctx.is_kids or allowed_for_kids(str(card.rating))
        }


class LibrarySignalsService:
    """Capability ``library.signals``."""

    def __init__(self, library: LibraryService) -> None:
        self._library = library

    def favorite_refs(self, profile_id: int, limit: int = 200) -> list[str]:
        return self._library.favorite_refs(profile_id, limit)

    def recent_refs(self, profile_id: int, limit: int = 50) -> list[str]:
        return self._library.recent_refs(profile_id, limit)
