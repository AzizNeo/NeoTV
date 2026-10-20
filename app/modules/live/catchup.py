"""The catch-up rule (ADR-0012), contributed to the playback gate as a policy.

A window of a live channel may be played when the channel is archived and the window starts no
earlier than ``min(channel archive_days, plan catchup_days)`` ago. Every player — web, TV apps,
the Xtream API — opens sessions through the same gate, so none can widen it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol

from app.kernel.capabilities import CapabilityIndex
from app.kernel.time import Clock
from app.modules.live.api import NAMESPACE
from app.modules.live.services import LiveChannelService
from app.modules.playback.api import ContentDescriptor, Deny, PlaybackContext


class _Entitlements(Protocol):  # consumer-owned port for the optional billing capability
    def for_user(self, user_id: int) -> Any: ...


class CatchupPolicy:
    name = "catchup_window"
    order = 30

    def __init__(self, channels: LiveChannelService, entitlements: _Entitlements | None, clock: Clock) -> None:
        self._channels = channels
        self._entitlements = entitlements
        self._clock = clock

    def evaluate(self, ctx: PlaybackContext, descriptor: ContentDescriptor) -> Deny | None:
        if ctx.window is None or descriptor.ref.namespace != NAMESPACE:
            return None
        channel_days = self._channels.archive_days(descriptor.ref.id)
        if channel_days <= 0:
            return Deny("CATCHUP_NOT_AVAILABLE", "This channel is not recorded for catch-up")
        # Without the billing module there are no plans: the channel's own window is the limit.
        plan_days = (
            int(getattr(self._entitlements.for_user(ctx.user_id), "catchup_days", 0))
            if self._entitlements is not None
            else channel_days
        )
        if plan_days <= 0:
            return Deny("CATCHUP_NOT_IN_PLAN", "Catch-up TV is not part of this plan")
        now = self._clock.now()
        if ctx.window.start >= now:
            return Deny("CATCHUP_NOT_STARTED", "This programme has not started yet")
        if ctx.window.start < now - timedelta(days=min(channel_days, plan_days)):
            return Deny("CATCHUP_TOO_OLD", "This programme is older than catch-up allows")
        return None


def build_catchup_policy(c: Any) -> CatchupPolicy:
    return CatchupPolicy(
        c.resolve(LiveChannelService), c.resolve(CapabilityIndex).optional("billing.entitlements"), c.resolve(Clock)
    )
