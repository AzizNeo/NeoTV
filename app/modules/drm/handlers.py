"""Event consumers of the drm module."""

from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.drm.services import LicenseService, ProtectionService
from app.shared_kernel.events import ContentRemoved, PlaybackSessionEnded


def on_playback_session_ended(event: PlaybackSessionEnded, *, uow: UnitOfWork) -> None:
    """Licenses live and die with their playback session (released, not revoked)."""
    resolve(LicenseService).release_session(uow.session, event.session_token)


def on_content_removed(event: ContentRemoved, *, uow: UnitOfWork) -> None:
    """Removed content: revoke its licenses and destroy its key (crypto-shredding)."""
    resolve(ProtectionService).remove_for_content(uow.session, event.content_ref)
