"""Event consumers feeding the recommendation read model."""

from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.recommendations.services import RecommendationService
from app.shared_kernel.events import ContentRemoved, PlaybackSessionStarted, ProfileDeleted


def on_playback_session_started(event: PlaybackSessionStarted, *, uow: UnitOfWork) -> None:
    resolve(RecommendationService).record_start(uow.session, event)


def on_content_removed(event: ContentRemoved, *, uow: UnitOfWork) -> None:
    RecommendationService.purge_content(uow.session, event.content_ref)


def on_profile_deleted(event: ProfileDeleted, *, uow: UnitOfWork) -> None:
    RecommendationService.purge_profile(uow.session, event.profile_id)
