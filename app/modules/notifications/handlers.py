"""Outbox consumer: ``fn(event, *, uow)`` — idempotent (inbox), never commits."""

from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.notifications.services import EmailDeliveryService
from app.shared_kernel.events import EmailQueued


def on_email_queued(event: EmailQueued, *, uow: UnitOfWork) -> None:
    resolve(EmailDeliveryService).deliver(uow, event.message_id)
