"""Event consumers of the billing module."""

from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWork
from app.modules.billing.services import SubscriptionRepository
from app.shared_kernel.events import UserRegistered


def on_user_registered(event: UserRegistered, *, uow: UnitOfWork) -> None:
    """Every account owns exactly one subscription row from day one (free tier).
    Idempotent: unique ``user_id`` + ON CONFLICT DO NOTHING."""
    SubscriptionRepository(uow.session).ensure(event.user_id, resolve(Clock).now())
