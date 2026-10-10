"""Event consumers: ``fn(event, *, uow)`` — idempotent, never commit (the kernel does)."""

from __future__ import annotations

from app.kernel.uow import UnitOfWork
from app.modules._template.services import TemplateService
from app.shared_kernel.events import UserStatusChanged


def on_user_status_changed(event: UserStatusChanged, *, uow: UnitOfWork) -> None:
    if not event.is_active:
        TemplateService.purge_user(uow, event.user_id)
