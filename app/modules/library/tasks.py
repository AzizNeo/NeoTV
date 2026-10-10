from __future__ import annotations

from celery import shared_task

from app.kernel.container import resolve
from app.modules.library.services import LibraryService


@shared_task(name="library.purge_old_history", ignore_result=True)
def purge_old_history() -> int:
    return resolve(LibraryService).purge_old_history()
