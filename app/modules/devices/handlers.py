from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.devices.services import DeviceService
from app.shared_kernel.events import NewDeviceSignedIn, UserLoggedIn


def on_user_logged_in(event: UserLoggedIn, *, uow: UnitOfWork) -> None:
    new_device = resolve(DeviceService).touch(
        session=uow.session,
        user_id=event.user_id,
        client_device_id=event.client_device_id,
        user_agent=event.user_agent,
        ip=event.ip,
    )
    if new_device is not None:
        # Same transaction as the inventory row: the alert exists iff the device was recorded.
        uow.outbox.add(
            NewDeviceSignedIn(
                user_id=event.user_id, device_label=new_device, ip=event.ip[:45], occurred_at=event.occurred_at
            )
        )
