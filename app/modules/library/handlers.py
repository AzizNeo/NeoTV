"""Event consumers of the library module."""

from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.library.services import LibraryService
from app.shared_kernel.events import ContentRemoved, PlaybackSessionEnded, ProfileDeleted


def on_playback_session_ended(event: PlaybackSessionEnded, *, uow: UnitOfWork) -> None:
    """History is derived from playback facts — the client cannot forge it.
    Idempotent on ``session_token`` (redelivery-safe)."""
    resolve(LibraryService).record_session(uow.session, event)


def on_content_removed(event: ContentRemoved, *, uow: UnitOfWork) -> None:
    LibraryService.purge_content(uow.session, event.content_ref)


def on_profile_deleted(event: ProfileDeleted, *, uow: UnitOfWork) -> None:
    LibraryService.purge_profile(uow.session, event.profile_id)
