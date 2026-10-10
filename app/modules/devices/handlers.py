from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.devices.services import DeviceService
from app.shared_kernel.events import UserLoggedIn


def on_user_logged_in(event: UserLoggedIn, *, uow: UnitOfWork) -> None:
    resolve(DeviceService).touch(
        session=uow.session,
        user_id=event.user_id,
        client_device_id=event.client_device_id,
        user_agent=event.user_agent,
        ip=event.ip,
    )
