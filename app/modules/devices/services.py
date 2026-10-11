from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.kernel.db import dialect_insert
from app.kernel.security.device_keys import DeviceKeys
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.devices.models import Device
from app.shared_kernel.events import DeviceRevoked
from app.shared_kernel.user_agent import parse_user_agent


class DeviceNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class DeviceView:
    id: int
    name: str
    device_type: str
    browser: str | None
    os: str | None
    is_trusted: bool
    is_current: bool
    login_count: int
    last_ip: str | None
    last_seen_at: datetime
    created_at: datetime


class DeviceService:
    def __init__(self, uow: UnitOfWorkFactory, keys: DeviceKeys, clock: Clock) -> None:
        self._uow = uow
        self._keys = keys
        self._clock = clock

    def current_key(self, user_id: int, client_device_id: str | None, user_agent: str | None) -> str:
        return self._keys.key(user_id, client_device_id, user_agent)

    def touch(
        self, *, session: Any, user_id: int, client_device_id: str | None, user_agent: str, ip: str
    ) -> str | None:
        """Atomic upsert on (user_id, device_key) — no read-then-insert race (RT-06).

        Returns the device's display name when this sign-in is the account's first from this device *and* the
        account already had another one (the very first device — signup — is not news). ``None`` otherwise.
        """
        agent = parse_user_agent(user_agent)
        now = self._clock.now()
        stmt = dialect_insert(session, Device.__table__).values(
            user_id=user_id,
            device_key=self._keys.key(user_id, client_device_id, user_agent),
            name=agent.display_name[:100],
            device_type=agent.device_type,
            browser=agent.browser,
            os=agent.os,
            is_trusted=False,
            is_active=True,
            login_count=1,
            last_ip=ip[:45],
            last_seen_at=now,
            created_at=now,
        )
        login_count = session.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "device_key"],
                set_={
                    "last_seen_at": now,
                    "last_ip": ip[:45],
                    "is_active": True,
                    "login_count": Device.__table__.c.login_count + 1,
                },
            ).returning(Device.__table__.c.login_count)  # 1 ⇔ this statement inserted the row
        ).scalar_one()
        if login_count != 1:
            return None
        others = session.execute(select(func.count(Device.id)).where(Device.user_id == user_id)).scalar_one()
        return agent.display_name[:100] if others > 1 else None

    def list(self, *, user_id: int, current_key: str) -> list[DeviceView]:
        with self._uow() as uow:
            rows = uow.session.execute(
                select(Device)
                .where(Device.user_id == user_id, Device.is_active.is_(True))
                .order_by(Device.last_seen_at.desc())
            ).scalars()
            return [self._view(d, current_key) for d in rows]

    def revoke(self, *, user_id: int, device_id: int) -> None:
        with self._uow() as uow:
            device = self._owned(uow.session, user_id, device_id)
            device.is_active = False
            device.is_trusted = False
            uow.outbox.add(
                DeviceRevoked(user_id=user_id, device_key=device.device_key, occurred_at=self._clock.now().isoformat())
            )

    def set_trusted(self, *, user_id: int, device_id: int, trusted: bool, current_key: str) -> DeviceView:
        with self._uow() as uow:
            device = self._owned(uow.session, user_id, device_id)
            device.is_trusted = trusted
            return self._view(device, current_key)

    def rename(self, *, user_id: int, device_id: int, name: str, current_key: str) -> DeviceView:
        with self._uow() as uow:
            device = self._owned(uow.session, user_id, device_id)
            device.name = name
            return self._view(device, current_key)

    def active_devices(self) -> int:
        with self._uow() as uow:
            return int(
                uow.session.execute(select(func.count(Device.id)).where(Device.is_active.is_(True))).scalar_one()
            )

    @staticmethod
    def _owned(session: Any, user_id: int, device_id: int) -> Device:
        device = session.get(Device, device_id)
        if device is None or device.user_id != user_id or not device.is_active:
            raise DeviceNotFoundError("Device not found")
        return device

    @staticmethod
    def _view(device: Device, current_key: str) -> DeviceView:
        return DeviceView(
            id=device.id,
            name=device.name,
            device_type=device.device_type,
            browser=device.browser,
            os=device.os,
            is_trusted=bool(device.is_trusted),
            is_current=device.device_key == current_key,
            login_count=device.login_count,
            last_ip=device.last_ip,
            last_seen_at=device.last_seen_at,
            created_at=device.created_at,
        )
