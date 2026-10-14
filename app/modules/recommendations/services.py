"""Recommendation read model + queries.

Write side: ``PlaybackSessionStarted`` → one upsert into the hourly bucket and
one into the profile's affinity (exactly-once per consumer via the kernel
inbox, so counters are not inflated by redelivery).

Read side: refs are computed and cached (Trending through ``StampedeGuard``,
For You per profile with a short TTL); *cards* are hydrated per request through
``playback.content`` so kids filtering and removed content are always current.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.kernel.cache.stampede import JsonCodec, StampedeGuard
from app.kernel.db import dialect_insert
from app.kernel.resilience.best_effort import best_effort
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.playback.api import ContentCard, ContentDirectory
from app.modules.recommendations.models import PlayBucket, ProfileAffinity
from app.shared_kernel.content import ContentRef
from app.shared_kernel.events import PlaybackSessionStarted
from app.shared_kernel.ratings import allowed_for_kids

BUCKET_RETENTION_DAYS = 30
FOR_YOU_TTL_S = 300
TOP_GROUPS = 3
CATALOG_NAMESPACE = "catalog"  # the namespace whose reader (catalog.read) knows about groups


class _CatalogReaderLike(Protocol):
    def similar(self, channel_id: int, limit: int) -> list[int]: ...
    def by_groups(self, groups: list[str], *, exclude_ids: list[int], limit: int) -> list[int]: ...


class _LibrarySignalsLike(Protocol):
    def favorite_refs(self, profile_id: int, limit: int = 200) -> list[str]: ...


class _CapabilitiesLike(Protocol):
    def optional(self, capability: str) -> Any | None: ...


#: Why an item is recommended — a *code* plus its subject, so every client words it in its own
#: language ("Because you like {subject}" / "{subject} sevdiğiniz için"). `reason` keeps the English
#: sentence for older clients.
REASON_TEXT = {
    "trending": "trending",
    "recommended": "recommended",
    "likes_group": "Because you like {subject}",
    "watched": "Because you watched {subject}",
}


def reason_text(code: str, subject: str | None) -> str:
    return REASON_TEXT.get(code, code).format(subject=subject or "")


@dataclass(frozen=True, slots=True)
class RecoCard:
    ref: str
    title: str
    image: str | None
    group: str | None
    kind: str
    rating: str
    reason_code: str
    reason_subject: str | None = None

    @property
    def reason(self) -> str:
        return reason_text(self.reason_code, self.reason_subject)


@dataclass(frozen=True, slots=True)
class Row:
    key: str
    title: str
    items: list[RecoCard]
    subject: str | None = None  # "because:<ref>" rows: the title that was watched


def _hour(at: datetime) -> datetime:
    return at.replace(minute=0, second=0, microsecond=0)


class RecommendationService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        content: ContentDirectory,
        capabilities: _CapabilitiesLike,
        trending_guard: StampedeGuard,
        redis: Any,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._content = content
        self._capabilities = capabilities
        self._trending = trending_guard
        self._redis = redis
        self._clock = clock

    # ── write side (event consumer, inside its UoW) ───────────────────────
    def record_start(self, session: Session, event: PlaybackSessionStarted) -> None:
        started = datetime.fromisoformat(event.started_at)
        session.execute(
            dialect_insert(session, PlayBucket.__table__)
            .values(content_ref=event.content_ref, bucket=_hour(started), plays=1)
            .on_conflict_do_update(
                index_elements=["content_ref", "bucket"], set_={"plays": PlayBucket.__table__.c.plays + 1}
            )
        )
        session.execute(
            dialect_insert(session, ProfileAffinity.__table__)
            .values(profile_id=event.profile_id, content_ref=event.content_ref, plays=1, last_played_at=started)
            .on_conflict_do_update(
                index_elements=["profile_id", "content_ref"],
                set_={"plays": ProfileAffinity.__table__.c.plays + 1, "last_played_at": started},
            )
        )

    @staticmethod
    def purge_content(session: Session, content_ref: str) -> None:
        session.execute(delete(PlayBucket).where(PlayBucket.content_ref == content_ref))
        session.execute(delete(ProfileAffinity).where(ProfileAffinity.content_ref == content_ref))

    @staticmethod
    def purge_profile(session: Session, profile_id: int) -> None:
        session.execute(delete(ProfileAffinity).where(ProfileAffinity.profile_id == profile_id))

    def purge_old_buckets(self, retention_days: int = BUCKET_RETENTION_DAYS) -> int:
        cutoff = self._clock.now() - timedelta(days=retention_days)
        with self._uow() as uow:
            return int(uow.session.execute(delete(PlayBucket).where(PlayBucket.bucket < cutoff)).rowcount or 0)

    # ── trending (capability recommendations.trending) ────────────────────
    def trending_refs(self, *, hours: int, limit: int) -> list[str]:
        """Cached globally per window; ``limit`` slices the cached top-100."""
        ranked = self._trending.get_or_compute(
            f"trending:{hours}h",
            lambda: self._compute_trending(hours, 100),
            JsonCodec[list[str]](),
        )
        return ranked[:limit]

    def _compute_trending(self, hours: int, limit: int) -> list[str]:
        since = _hour(self._clock.now() - timedelta(hours=hours))
        total = func.sum(PlayBucket.plays).label("total")
        with self._uow() as uow:
            return [
                row.content_ref
                for row in uow.session.execute(
                    select(PlayBucket.content_ref, total)
                    .where(PlayBucket.bucket >= since)
                    .group_by(PlayBucket.content_ref)
                    .order_by(total.desc(), PlayBucket.content_ref)
                    .limit(limit)
                ).all()
            ]

    def trending(self, *, is_kids: bool, hours: int, limit: int) -> Row:
        # Over-fetch: kids filtering / removed content may drop some.
        refs = self.trending_refs(hours=hours, limit=limit * 3)
        return Row("trending", "Trending Now", self._hydrate(refs, is_kids, limit, lambda _c: ("trending", None)))

    # ── personalised ──────────────────────────────────────────────────────
    def for_you(self, *, profile_id: int, is_kids: bool, limit: int) -> Row:
        cache_key = f"reco:for_you:{profile_id}:{int(is_kids)}:{limit}"
        cached = best_effort(lambda: self._redis.get(cache_key), op="reco.for_you.cache_get")
        if cached:
            pairs = json.loads(cached)
        else:
            pairs = self._compute_for_you(profile_id, is_kids, limit)
            best_effort(
                lambda: self._redis.set(cache_key, json.dumps(pairs), ex=FOR_YOU_TTL_S), op="reco.for_you.cache_set"
            )
        # [ref, code, subject]; a pre-upgrade cache entry is [ref, sentence] → shown as "recommended".
        reasons = {p[0]: (p[1], p[2]) if len(p) == 3 else ("recommended", None) for p in pairs}
        items = self._hydrate(
            [p[0] for p in pairs], is_kids, limit, lambda c: reasons.get(c.ref, ("recommended", None))
        )
        if not items:  # cold start → popular content
            return Row("for_you", "For You", self.trending(is_kids=is_kids, hours=24 * 7, limit=limit).items)
        return Row("for_you", "For You", items)

    def _compute_for_you(self, profile_id: int, is_kids: bool, limit: int) -> list[tuple[str, str, str | None]]:
        catalog: _CatalogReaderLike | None = self._capabilities.optional("catalog.read")
        if catalog is None:
            return []
        seen = self._affinity_refs(profile_id, limit=200)
        library: _LibrarySignalsLike | None = self._capabilities.optional("library.signals")
        favorites = library.favorite_refs(profile_id, 200) if library is not None else []
        signals = list(dict.fromkeys(favorites + seen))
        if not signals:
            return []
        cards = self._content.cards(signals)
        weights: Counter[str] = Counter()
        for ref in signals:
            card = cards.get(ref)
            if card is not None and card.group:
                weights[card.group] += 2 if ref in favorites else 1
        groups = [g for g, _ in weights.most_common(TOP_GROUPS)]
        if not groups:
            return []
        exclude = [ContentRef.parse(r).id for r in signals if r.startswith(f"{CATALOG_NAMESPACE}:")]
        per_group = max(1, (limit * 2) // len(groups))
        pairs: list[tuple[str, str, str | None]] = []
        for group in groups:
            for channel_id in catalog.by_groups([group], exclude_ids=exclude, limit=per_group):
                pairs.append((f"{CATALOG_NAMESPACE}:{channel_id}", "likes_group", group))
        return list(dict.fromkeys(pairs))[: limit * 2]

    def because_you_watched(self, *, profile_id: int, is_kids: bool, limit: int) -> Row | None:
        catalog: _CatalogReaderLike | None = self._capabilities.optional("catalog.read")
        if catalog is None:
            return None
        for ref in self._affinity_refs(profile_id, limit=10):
            parsed = ContentRef.parse(ref)
            if parsed.namespace != CATALOG_NAMESPACE:
                continue
            source = self._content.cards([ref]).get(ref)
            if source is None or (is_kids and not allowed_for_kids(str(source.rating))):
                continue
            similar = [f"{CATALOG_NAMESPACE}:{i}" for i in catalog.similar(parsed.id, limit * 2)]
            why = ("watched", source.title)
            items = self._hydrate(similar, is_kids, limit, lambda _c, why=why: why)
            if items:
                return Row(f"because:{ref}", reason_text(*why), items, subject=source.title)
        return None

    def home(self, *, profile_id: int, is_kids: bool, limit: int) -> list[Row]:
        rows = [self.for_you(profile_id=profile_id, is_kids=is_kids, limit=limit)]
        because = self.because_you_watched(profile_id=profile_id, is_kids=is_kids, limit=limit)
        if because is not None:
            rows.append(because)
        rows.append(self.trending(is_kids=is_kids, hours=24, limit=limit))
        return [r for r in rows if r.items]

    # ── helpers ───────────────────────────────────────────────────────────
    def _affinity_refs(self, profile_id: int, *, limit: int) -> list[str]:
        with self._uow() as uow:
            return list(
                uow.session.execute(
                    select(ProfileAffinity.content_ref)
                    .where(ProfileAffinity.profile_id == profile_id)
                    .order_by(ProfileAffinity.last_played_at.desc())
                    .limit(limit)
                ).scalars()
            )

    def _hydrate(self, refs: list[str], is_kids: bool, limit: int, reason: Any) -> list[RecoCard]:
        if not refs:
            return []
        cards: dict[str, ContentCard] = self._content.cards(list(dict.fromkeys(refs)))
        out: list[RecoCard] = []
        for ref in dict.fromkeys(refs):
            card = cards.get(ref)
            if card is None or (is_kids and not allowed_for_kids(str(card.rating))):
                continue
            out.append(
                RecoCard(card.ref, card.title, card.image, card.group, str(card.kind), str(card.rating), *reason(card))
            )
            if len(out) >= limit:
                break
        return out
