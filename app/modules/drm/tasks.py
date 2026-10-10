from __future__ import annotations

from celery import shared_task

from app.kernel.container import resolve
from app.modules.drm.services import LicenseService


@shared_task(name="drm.expire_licenses", ignore_result=True)
def expire_licenses() -> int:
    return resolve(LicenseService).expire_due()


@shared_task(name="drm.purge_events", ignore_result=True)
def purge_events() -> int:
    return resolve(LicenseService).purge_events()
