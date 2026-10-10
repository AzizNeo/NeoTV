from __future__ import annotations

from datetime import timedelta

from celery import shared_task

from app.kernel.container import resolve
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.notifications.services import EmailDeliveryService

REDACT_AFTER = timedelta(hours=24)


@shared_task(name="notifications.redact_stale", ignore_result=True)
def redact_stale() -> int:
    """Defence in depth: no message keeps its (possibly secret) context past 24h,
    including ones the outbox dead-lettered."""
    clock = resolve(Clock)
    with resolve(UnitOfWorkFactory)() as uow:
        return EmailDeliveryService.redact_stale(uow, older_than=REDACT_AFTER, now_fn=clock.now)
