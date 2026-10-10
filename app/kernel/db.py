"""Persistence primitives shared by every module.

* ``db``: Flask-SQLAlchemy with a **naming convention** — every constraint and
  index gets a deterministic name, which keeps Alembic (and SQLite batch mode)
  deterministic across dialects.
* ``UTCDateTime``: stores UTC, always returns *aware* UTC datetimes on every
  dialect (SQLite returns naive values natively).
* SQLite pragmas (WAL, busy timeout, FK enforcement) applied on connect.
* ``dialect_insert``: dialect-correct INSERT for ``ON CONFLICT`` upserts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import DateTime, MetaData, event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.orm import Session
from sqlalchemy.types import TypeDecorator

from app.kernel.time import utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate(compare_type=True, render_as_batch=True)


class UTCDateTime(TypeDecorator[datetime]):
    """Aware-UTC in, aware-UTC out — on PostgreSQL *and* SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime refuses naive datetimes; use app.kernel.time.utcnow()")
        value = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def created_at_column(**kwargs: Any) -> Any:
    return db.Column(UTCDateTime(), nullable=False, default=utcnow, **kwargs)


def updated_at_column(**kwargs: Any) -> Any:
    return db.Column(UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow, **kwargs)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def pairs(rows: Any) -> dict[Any, Any]:
    """``{first_column: second_column}`` for a 2-column result (typed alternative to ``dict(rows)``)."""
    return {row[0]: row[1] for row in rows}


def dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name


def dialect_insert(session: Session, table: Any) -> Any:
    """INSERT construct supporting ``on_conflict_do_*`` for the active dialect.

    To learn whether a row was actually inserted, use ``.returning(<pk>)`` and
    test ``.first() is not None`` — never ``rowcount``: psycopg 3 reports -1
    for INSERT statements (``tests/integration`` guards this on PostgreSQL)."""
    name = dialect_name(session)
    if name == "postgresql":
        return postgresql.insert(table)
    if name == "sqlite":
        return sqlite.insert(table)
    raise NotImplementedError(f"upsert is not implemented for dialect '{name}'")
