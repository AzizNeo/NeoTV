"""Outbox writer / claimer and inbox — dialect aware (PostgreSQL & SQLite)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.kernel.db import dialect_insert, dialect_name
from app.kernel.events.registry import EventRegistry
from app.kernel.outbox.models import DeadLetter, InboxRecord, OutboxRecord, OutboxStatus
from app.kernel.time import utcnow

PENDING_FLAG = "outbox_pending"

_CLAIM_POSTGRES = text(
    """
    UPDATE kernel_outbox
       SET status = :dispatching, claimed_at = :now, attempts = attempts + 1
     WHERE id IN (
            SELECT id FROM kernel_outbox
             WHERE status = :pending AND available_at <= :now
             ORDER BY created_at
             LIMIT :limit
             FOR UPDATE SKIP LOCKED)
    RETURNING id, event_name
    """
)


class OutboxWriter:
    """Adds events to the caller's transaction. Never commits."""

    def __init__(self, session: Session, registry: EventRegistry) -> None:
        self._session = session
        self._registry = registry

    def add(self, event: Any) -> str:
        name, version, payload = self._registry.encode(event)
        record = OutboxRecord(event_name=name, event_version=version, payload_json=payload)
        self._session.add(record)
        self._session.flush([record])
        self._session.info[PENDING_FLAG] = True
        return record.id


class OutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def claim(self, limit: int) -> list[tuple[str, str]]:
        now = utcnow()
        params = {
            "dispatching": OutboxStatus.DISPATCHING,
            "pending": OutboxStatus.PENDING,
            "now": now,
            "limit": limit,
        }
        if dialect_name(self._session) == "postgresql":
            rows = self._session.execute(_CLAIM_POSTGRES, params).all()
            return [(r[0], r[1]) for r in rows]
        # SQLite: single writer → a SELECT followed by a guarded UPDATE is race-free.
        candidates = self._session.execute(
            select(OutboxRecord.id, OutboxRecord.event_name)
            .where(OutboxRecord.status == OutboxStatus.PENDING, OutboxRecord.available_at <= now)
            .order_by(OutboxRecord.created_at)
            .limit(limit)
        ).all()
        claimed: list[tuple[str, str]] = []
        for event_id, event_name in candidates:
            result = self._session.execute(
                update(OutboxRecord)
                .where(OutboxRecord.id == event_id, OutboxRecord.status == OutboxStatus.PENDING)
                .values(status=OutboxStatus.DISPATCHING, claimed_at=now, attempts=OutboxRecord.attempts + 1)
            )
            if result.rowcount == 1:
                claimed.append((event_id, event_name))
        return claimed

    def mark(self, event_id: str, status: str) -> None:
        values: dict[str, Any] = {"status": status}
        if status == OutboxStatus.DISPATCHED:
            values["dispatched_at"] = utcnow()
        self._session.execute(update(OutboxRecord).where(OutboxRecord.id == event_id).values(**values))

    def get(self, event_id: str) -> OutboxRecord | None:
        return self._session.get(OutboxRecord, event_id)

    def release_stuck(self, older_than: timedelta) -> int:
        cutoff = utcnow() - older_than
        result = self._session.execute(
            update(OutboxRecord)
            .where(OutboxRecord.status == OutboxStatus.DISPATCHING, OutboxRecord.claimed_at < cutoff)
            .values(status=OutboxStatus.PENDING, claimed_at=None)
        )
        return int(result.rowcount or 0)

    def purge(self, older_than: timedelta) -> int:
        cutoff = utcnow() - older_than
        result = self._session.execute(
            delete(OutboxRecord).where(
                OutboxRecord.status.in_([OutboxStatus.DISPATCHED, OutboxStatus.NO_CONSUMER]),
                OutboxRecord.created_at < cutoff,
            )
        )
        self._session.execute(delete(InboxRecord).where(InboxRecord.processed_at < cutoff))
        return int(result.rowcount or 0)

    def lag_seconds(self) -> float:
        oldest = self._session.execute(
            select(OutboxRecord.created_at)
            .where(OutboxRecord.status == OutboxStatus.PENDING)
            .order_by(OutboxRecord.created_at)
            .limit(1)
        ).scalar_one_or_none()
        return 0.0 if oldest is None else max(0.0, (utcnow() - oldest).total_seconds())


class InboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def try_claim(self, event_id: str, consumer: str) -> bool:
        stmt = (
            dialect_insert(self._session, InboxRecord.__table__)
            .values(event_id=event_id, consumer=consumer, processed_at=utcnow())
            .on_conflict_do_nothing(index_elements=["event_id", "consumer"])
            .returning(InboxRecord.__table__.c.event_id)
        )
        # RETURNING, not rowcount: INSERT rowcount is -1 on psycopg 3 (see app.kernel.db.dialect_insert).
        return self._session.execute(stmt).first() is not None


class DeadLetterRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, *, event_id: str, consumer: str, error: str) -> None:
        stmt = (
            dialect_insert(self._session, DeadLetter.__table__)
            .values(event_id=event_id, consumer=consumer, error=error[:4000], failed_at=utcnow())
            .on_conflict_do_update(
                index_elements=["event_id", "consumer"],
                set_={"error": error[:4000], "failed_at": utcnow(), "resolved_at": None},
            )
        )
        self._session.execute(stmt)

    def open_count(self) -> int:
        from sqlalchemy import func

        return int(
            self._session.execute(
                select(func.count()).select_from(DeadLetter).where(DeadLetter.resolved_at.is_(None))
            ).scalar_one()
        )
