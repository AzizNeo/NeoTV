from __future__ import annotations

from app.kernel.time import utcnow
from app.kernel.uow import UnitOfWork
from app.modules.profile.services import ProfileRepository
from app.shared_kernel.events import UserRegistered


def on_user_registered(event: UserRegistered, *, uow: UnitOfWork) -> None:
    """Every account starts with a main profile (idempotent: get-or-create)."""
    ProfileRepository(uow.session).ensure_default(event.user_id, utcnow())
