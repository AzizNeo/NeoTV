"""Outbox pipeline tasks.

dispatch  — claims pending events and fans out one ``deliver`` task per
            (event, consumer); never executes business code itself.
deliver   — runs exactly one consumer inside a Unit of Work together with its
            inbox claim → the consumer's effect and the "processed" marker
            commit atomically (exactly-once effect on at-least-once delivery).
            Failures retry with exponential back-off + jitter, then land in
            ``kernel_dead_letters`` (visible, alertable — never silent).
reap      — returns events stuck in 'dispatching' (crashed dispatcher) to 'pending'.
purge     — deletes old dispatched events and inbox markers.
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import cast

from celery import shared_task
from sqlalchemy.orm import Session

from app.kernel.container import container
from app.kernel.db import db
from app.kernel.events.bus import EventBus
from app.kernel.events.registry import EventRegistry
from app.kernel.outbox.models import OutboxStatus
from app.kernel.outbox.repository import PENDING_FLAG, DeadLetterRepository, OutboxRepository
from app.kernel.uow import UnitOfWork


def _session() -> Session:
    """The Flask-SQLAlchemy scoped session (one per worker thread / app context)."""
    return cast(Session, db.session)


_log = logging.getLogger("kernel.outbox")

MAX_DELIVERY_RETRIES = 8


@shared_task(name="kernel.outbox.dispatch", ignore_result=True)
def dispatch_outbox(batch: int = 200) -> int:
    bus = container().resolve(EventBus)
    session = _session()
    repo = OutboxRepository(session)
    claimed = repo.claim(batch)
    session.commit()

    fanned_out = 0
    for event_id, event_name in claimed:
        subscriptions = bus.consumers(event_name)
        if not subscriptions:
            repo.mark(event_id, OutboxStatus.NO_CONSUMER)
            session.commit()
            _log.warning("outbox.no_consumer event=%s id=%s", event_name, event_id)
            continue
        for sub in subscriptions:
            deliver_event.apply_async(args=(event_id, sub.consumer), queue=sub.queue)
            fanned_out += 1
        repo.mark(event_id, OutboxStatus.DISPATCHED)
        session.commit()
    return fanned_out


@shared_task(bind=True, name="kernel.outbox.deliver", acks_late=True, max_retries=MAX_DELIVERY_RETRIES)
def deliver_event(self, event_id: str, consumer: str) -> str:  # type: ignore[no-untyped-def]
    c = container()
    bus = c.resolve(EventBus)
    registry = c.resolve(EventRegistry)
    session = _session()

    record = OutboxRepository(session).get(event_id)
    if record is None:
        _log.info("outbox.deliver.missing id=%s consumer=%s (purged)", event_id, consumer)
        return "missing"
    subscription = bus.subscription(record.event_name, consumer)
    event = registry.decode(record.event_name, record.event_version, record.payload_json)
    session.commit()  # end the read transaction before opening the unit of work

    try:
        with UnitOfWork(session, registry) as uow:
            if not uow.inbox.try_claim(event_id, consumer):
                return "duplicate"
            subscription.handler(event, uow=uow)
    except Exception as exc:
        session.rollback()
        retries = self.request.retries or 0
        if retries >= MAX_DELIVERY_RETRIES:
            DeadLetterRepository(session).record(event_id=event_id, consumer=consumer, error=repr(exc))
            session.commit()
            _log.error("outbox.dead_letter event=%s id=%s consumer=%s", record.event_name, event_id, consumer)
            raise
        countdown = min(600, (2**retries) * 5) + random.uniform(0, 3)
        _log.warning("outbox.retry event=%s consumer=%s attempt=%s err=%r", record.event_name, consumer, retries, exc)
        raise self.retry(exc=exc, countdown=countdown) from exc
    if session.info.pop(PENDING_FLAG, False):  # the consumer emitted follow-up events
        dispatch_outbox.apply_async()
    return "delivered"


@shared_task(name="kernel.outbox.reap_stuck", ignore_result=True)
def reap_stuck(minutes: int = 5) -> int:
    session = _session()
    released = OutboxRepository(session).release_stuck(timedelta(minutes=minutes))
    session.commit()
    if released:
        _log.warning("outbox.reaped count=%s", released)
    return released


@shared_task(name="kernel.outbox.purge", ignore_result=True)
def purge(days: int = 7) -> int:
    session = _session()
    deleted = OutboxRepository(session).purge(timedelta(days=days))
    session.commit()
    return deleted


KERNEL_BEAT_SCHEDULE = {
    "kernel.outbox.dispatch": {"task": "kernel.outbox.dispatch", "schedule": 5.0},
    "kernel.outbox.reap_stuck": {"task": "kernel.outbox.reap_stuck", "schedule": 60.0},
    "kernel.outbox.purge": {"task": "kernel.outbox.purge", "schedule": 24 * 3600.0},
}
