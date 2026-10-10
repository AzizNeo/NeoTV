"""Real PostgreSQL + Redis backends (CI service containers / local servers).

    TEST_DATABASE_URL=postgresql://neotv:neotv@localhost:5432/neotv_test
    TEST_REDIS_URL=redis://localhost:6379/15

The same end-to-end scenarios that run on SQLite + fakeredis are re-collected
here against the production engines: dialect-specific paths (ON CONFLICT …
RETURNING, SKIP LOCKED, partial indexes, Lua scripts) only prove themselves
on the real thing — a psycopg-only INSERT rowcount bug was caught exactly so.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import redis
import sqlalchemy as sa
from flask import Flask

from app.kernel.db import db
from tests.support.factory import integration_urls, make_app


def _urls() -> tuple[str, str]:
    urls = integration_urls()
    if urls is None:
        pytest.skip("TEST_DATABASE_URL / TEST_REDIS_URL not set")
    return urls


def _reset_postgres(url: str) -> None:
    engine = sa.create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture
def app() -> Iterator[Flask]:
    db_url, redis_url = _urls()
    _reset_postgres(db_url)
    redis.Redis.from_url(redis_url).flushdb()
    flask_app = make_app(database_url=db_url, redis_url=redis_url)
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def file_app() -> Iterator[Flask]:
    """PostgreSQL stand-in for the migration tests' SQLite file database."""
    db_url, redis_url = _urls()
    _reset_postgres(db_url)
    flask_app = make_app(schema="none", database_url=db_url, redis_url=redis_url)
    with flask_app.app_context():
        yield flask_app
        db.session.remove()
        db.engine.dispose()
