"""Built-in abuse rules (contributed to ``admin.abuse_rules`` like any other)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.kernel.uow import UnitOfWorkFactory
from app.modules.admin.api import AbuseFinding
from app.modules.admin.models import LoginSignal


class _DistinctLoginRule:
    """Flags accounts whose logins in ``window`` span >= ``threshold`` distinct values of ``column``."""

    name = ""
    column_name = (
        ""  # attribute of LoginSignal (a name, not the descriptor: class-level ORM attributes bind to instances)
    )
    noun = ""

    def __init__(self, uow: UnitOfWorkFactory, *, threshold: int, window: timedelta) -> None:
        if threshold < 2:
            raise ValueError("threshold must be >= 2")
        self._uow = uow
        self._threshold = threshold
        self._window = window

    def evaluate(self, now: datetime) -> list[AbuseFinding]:
        distinct = func.count(func.distinct(getattr(LoginSignal, self.column_name))).label("n")
        with self._uow() as uow:
            rows = uow.session.execute(
                select(LoginSignal.user_id, distinct)
                .where(LoginSignal.occurred_at >= now - self._window)
                .group_by(LoginSignal.user_id)
                .having(distinct >= self._threshold)
            ).all()
        hours = int(self._window.total_seconds() // 3600)
        return [
            AbuseFinding(row.user_id, self.name, int(row.n), f"{row.n} distinct {self.noun} in the last {hours}h")
            for row in rows
        ]


class ManyIpsRule(_DistinctLoginRule):
    """Account sharing / credential stuffing signal."""

    name = "many_ips"
    column_name = "ip"
    noun = "IP addresses"


class ManyDevicesRule(_DistinctLoginRule):
    name = "many_devices"
    column_name = "device_hash"
    noun = "devices"


def build_many_ips_rule(c: Any) -> ManyIpsRule:
    return ManyIpsRule(c.resolve(UnitOfWorkFactory), threshold=5, window=timedelta(hours=24))


def build_many_devices_rule(c: Any) -> ManyDevicesRule:
    return ManyDevicesRule(c.resolve(UnitOfWorkFactory), threshold=6, window=timedelta(hours=24))
