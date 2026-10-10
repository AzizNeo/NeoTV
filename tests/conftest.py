"""Shared fixtures.

Default backend: in-memory SQLite + fakeredis, Celery eager — fast and
hermetic. Tests marked ``integration`` run against real PostgreSQL + Redis
(``TEST_DATABASE_URL`` / ``TEST_REDIS_URL``) and are skipped without them.
"""

from __future__ import annotations

import pytest
from flask import Flask

from tests.support.client import Api
from tests.support.factory import integration_urls, make_app

# The legacy checkout ships a stale co-located test; tools/cleanup_legacy removes it.
collect_ignore = ["test_validation_fix.py"]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if integration_urls() is None:
        skip = pytest.mark.skip(reason="TEST_DATABASE_URL / TEST_REDIS_URL not set")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def app() -> Flask:
    """No app context is held: each request (and each explicit
    ``with app.app_context()``) gets its own, exactly as in production."""
    return make_app()


@pytest.fixture
def api(app: Flask) -> Api:
    return Api(app)


@pytest.fixture
def admin(api: Api) -> str:
    return api.user("admin1", role="admin")


@pytest.fixture
def viewer(api: Api) -> str:
    return api.user("viewer1")
