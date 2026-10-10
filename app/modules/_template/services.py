from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select

from app.kernel.time import Clock
from app.kernel.uow import UnitOfWork, UnitOfWorkFactory
from app.modules._template.domain import TemplateItemNotFoundError, normalise_title
from app.modules._template.models import TemplateItem


@dataclass(frozen=True, slots=True)
class ItemView:
    id: int
    title: str
    created_at: datetime


class TemplateService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def list(self, user_id: int) -> list[ItemView]:
        with self._uow() as uow:
            rows = uow.session.execute(
                select(TemplateItem).where(TemplateItem.user_id == user_id).order_by(TemplateItem.id.desc())
            ).scalars()
            return [ItemView(r.id, r.title, r.created_at) for r in rows]

    def create(self, user_id: int, title: str) -> ItemView:
        with self._uow() as uow:
            row = TemplateItem(user_id=user_id, title=normalise_title(title), created_at=self._clock.now())
            uow.session.add(row)
            uow.flush()
            return ItemView(row.id, row.title, row.created_at)

    def delete(self, user_id: int, item_id: int) -> None:
        with self._uow() as uow:
            deleted = uow.session.execute(
                delete(TemplateItem).where(TemplateItem.id == item_id, TemplateItem.user_id == user_id)
            ).rowcount
            if not deleted:
                raise TemplateItemNotFoundError("item not found")

    def count_for(self, user_id: int) -> int:
        with self._uow() as uow:
            return int(
                uow.session.execute(
                    select(func.count(TemplateItem.id)).where(TemplateItem.user_id == user_id)
                ).scalar_one()
            )

    @staticmethod
    def purge_user(uow: UnitOfWork, user_id: int) -> None:
        uow.session.execute(delete(TemplateItem).where(TemplateItem.user_id == user_id))
