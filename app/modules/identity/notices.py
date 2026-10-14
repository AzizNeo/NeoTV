"""Security notices: plain e-mails that tell the owner something happened to the account.

No links, no tokens — just "this happened; if it wasn't you, do X". Every notice is
an outbox consumer (asynchronous, retried) and de-duplicated per event, so a
redelivered event never mails twice. Without the notifications module they are
skipped: the action itself must never depend on mail.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.kernel.uow import UnitOfWork
from app.modules.identity.emails import NEW_DEVICE_SIGN_IN, PASSWORD_CHANGED
from app.modules.identity.recovery import Mailer
from app.modules.identity.repository import UserRepository
from app.shared_kernel.events import NewDeviceSignedIn, PasswordChanged


class SecurityNotices:
    def __init__(self, *, mailer: Callable[[], Mailer | None]) -> None:
        self._mailer = mailer

    def password_changed(self, uow: UnitOfWork, event: PasswordChanged) -> None:
        self._send(
            uow, event.user_id, PASSWORD_CHANGED, {}, f"{PasswordChanged.NAME}:{event.user_id}:{event.occurred_at}"
        )

    def new_device(self, uow: UnitOfWork, event: NewDeviceSignedIn) -> None:
        when = datetime.fromisoformat(event.occurred_at).strftime("%Y-%m-%d %H:%M UTC")  # unambiguous in every language
        self._send(
            uow,
            event.user_id,
            NEW_DEVICE_SIGN_IN,
            {"device": event.device_label, "ip": event.ip, "when": when},
            f"{NewDeviceSignedIn.NAME}:{event.user_id}:{event.occurred_at}:{event.device_label}",
        )

    def _send(self, uow: UnitOfWork, user_id: int, template: str, context: dict[str, str], dedupe_key: str) -> None:
        mailer = self._mailer()
        user = UserRepository(uow.session).get(user_id)
        if mailer is None or user is None or not user.email or not user.is_active:
            return
        mailer.queue(
            to=user.email,
            template=template,
            context={"username": user.username, **context},
            dedupe_key=dedupe_key,
            locale=user.locale,
        )
