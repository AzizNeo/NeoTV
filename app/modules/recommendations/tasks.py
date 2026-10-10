from __future__ import annotations

from celery import shared_task

from app.kernel.container import resolve
from app.modules.recommendations.services import RecommendationService


@shared_task(name="recommendations.purge_old_buckets", ignore_result=True)
def purge_old_buckets() -> int:
    return resolve(RecommendationService).purge_old_buckets()
