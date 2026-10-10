from __future__ import annotations

from celery import shared_task

from app.kernel.container import resolve
from app.modules.billing.services import BillingService


@shared_task(name="billing.expire_due_subscriptions", ignore_result=True)
def expire_due_subscriptions() -> int:
    return resolve(BillingService).expire_due()
