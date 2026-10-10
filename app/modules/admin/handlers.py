"""Event consumers of the admin module."""

from __future__ import annotations

from app.kernel.uow import UnitOfWork
from app.modules.admin.services import AbuseService
from app.shared_kernel.events import UserLoggedIn


def on_user_logged_in(event: UserLoggedIn, *, uow: UnitOfWork) -> None:
    AbuseService.record_login(uow.session, event)
