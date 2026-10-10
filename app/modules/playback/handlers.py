"""Playback reacts to account/device lifecycle events."""

from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.playback.services import PlaybackSessionService
from app.shared_kernel.events import DeviceRevoked, SubscriptionChanged, UserStatusChanged


def on_user_status_changed(event: UserStatusChanged, *, uow: UnitOfWork) -> None:
    if not event.is_active:
        resolve(PlaybackSessionService).release_user(event.user_id, reason="suspended")


def on_device_revoked(event: DeviceRevoked, *, uow: UnitOfWork) -> None:
    resolve(PlaybackSessionService).release_device(event.user_id, event.device_key, reason="device_revoked")


def on_subscription_changed(event: SubscriptionChanged, *, uow: UnitOfWork) -> None:
    """A downgrade takes effect on running streams too, not only on the next open."""
    resolve(PlaybackSessionService).enforce_limit(event.user_id, event.max_streams, reason="plan_changed")
