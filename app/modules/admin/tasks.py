from __future__ import annotations

from celery import shared_task

from app.kernel.container import resolve
from app.modules.admin.services import AbuseService


@shared_task(name="admin.evaluate_abuse", ignore_result=True)
def evaluate_abuse() -> int:
    return resolve(AbuseService).evaluate()
