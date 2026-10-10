from __future__ import annotations

from celery import shared_task


@shared_task(name="_template.heartbeat", ignore_result=True)
def heartbeat() -> str:
    return "ok"
