"""Test application factory: isolated SQLite + in-process Redis per app."""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterable
from typing import Any

from flask import Flask

from app.kernel.settings import Settings

_counter = itertools.count()
TEST_SECRET = "test-secret-key-0123456789-abcdefghijklmnop"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "env": "test",
        "secret_key": TEST_SECRET,
        "database_url": "sqlite:///:memory:",
        "redis_url": f"fakeredis://t{next(_counter)}",
        "celery_broker_url": "memory://",
        "celery_result_backend": "cache+memory://",
        "celery_always_eager": True,
        "log_level": "WARNING",
        "email_backend": "memory",
    }
    values.update(overrides)
    return Settings(**values)


def make_app(*, installed: Iterable[str] | None = None, schema: str = "create_all", **overrides: Any) -> Flask:
    """``installed``: override INSTALLED_MODULES (short names). ``schema``:
    ``create_all`` (fast) or ``migrate`` (runs the Alembic chain) or ``none``."""
    import app.modules as modules_pkg
    from app import create_app
    from app.kernel.db import db

    original = modules_pkg.INSTALLED_MODULES
    if installed is not None:
        modules_pkg.INSTALLED_MODULES = tuple(f"app.modules.{name}" for name in installed)
    try:
        flask_app = create_app(make_settings(**overrides))
    finally:
        modules_pkg.INSTALLED_MODULES = original
    with flask_app.app_context():
        if schema == "create_all":
            db.drop_all()
            db.create_all()
        elif schema == "migrate":
            import flask_migrate

            flask_migrate.upgrade()
    return flask_app


def integration_urls() -> tuple[str, str] | None:
    db_url, redis_url = os.environ.get("TEST_DATABASE_URL"), os.environ.get("TEST_REDIS_URL")
    return (db_url, redis_url) if db_url and redis_url else None
