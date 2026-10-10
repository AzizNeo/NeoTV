"""Deterministic app instance for contract generation (independent of the local .env).

flask --app tools.openapi_app kernel openapi --out openapi/openapi.json
"""

from __future__ import annotations

from app import create_app
from app.kernel.settings import Settings

app = create_app(
    Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        secret_key="openapi-generation-only-not-a-real-secret-0000",  # noqa: S106 - throwaway, never serves traffic
        database_url="sqlite:///:memory:",
        redis_url="fakeredis://openapi",
        celery_broker_url="memory://",
        celery_result_backend="cache+memory://",
        celery_always_eager=True,
        log_level="WARNING",
    )
)
