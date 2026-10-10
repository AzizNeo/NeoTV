"""Unit of Work — the single transaction boundary for application services.

* Re-entrant: nested ``with uow:`` blocks join the outermost transaction; only
  the outermost block commits (no accidental early commits when one service
  calls another).
* Exposes ``outbox`` so that domain changes and their integration events are
  committed atomically (transactional outbox).
"""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from app.kernel.events.registry import EventRegistry
from app.kernel.outbox.repository import InboxRepository, OutboxWriter

_DEPTH = "uow_depth"


class UnitOfWork:
    def __init__(self, session: Session, registry: EventRegistry) -> None:
        self.session = session
        self.outbox = OutboxWriter(session, registry)
        self.inbox = InboxRepository(session)

    def __enter__(self) -> UnitOfWork:
        self.session.info[_DEPTH] = self.session.info.get(_DEPTH, 0) + 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        depth = self.session.info.get(_DEPTH, 1) - 1
        self.session.info[_DEPTH] = depth
        if exc_type is not None:
            if depth == 0:
                self.session.rollback()
            return
        if depth == 0:
            self.session.commit()

    def flush(self) -> None:
        self.session.flush()


class UnitOfWorkFactory:
    """Injected into services: ``with self._uow() as uow: ...``."""

    def __init__(self, registry: EventRegistry, session_provider: object | None = None) -> None:
        self._registry = registry
        self._session_provider = session_provider

    def __call__(self) -> UnitOfWork:
        from app.kernel.db import db

        session = self._session_provider() if callable(self._session_provider) else db.session
        return UnitOfWork(session, self._registry)  # type: ignore[arg-type]
