from __future__ import annotations

from celery import shared_task

from app.kernel.container import resolve
from app.modules.playback.services import PlaybackSessionService


@shared_task(name="playback.expire_stale_sessions", ignore_result=True)
def expire_stale_sessions() -> int:
    return resolve(PlaybackSessionService).expire_stale()
