"""Health endpoints for orchestrators and the frontend feature registry."""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app
from sqlalchemy import text

from app.kernel.container import resolve
from app.kernel.db import db
from app.kernel.http.errors import error_response
from app.kernel.http.responses import ok
from app.kernel.settings import PROJECT_ROOT, Settings

_log = logging.getLogger("kernel.health")
blueprint = Blueprint("kernel_health", __name__)

APP_VERSION = "2.0.0"


def _migration_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(PROJECT_ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


@blueprint.get("/live")
def live() -> Any:
    return ok({"status": "alive"})


@blueprint.get("/ready")
def ready() -> Any:
    checks: dict[str, str] = {}
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error:{type(exc).__name__}"
    try:
        resolve("kernel.redis").ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error:{type(exc).__name__}"
    try:
        current = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        head = _migration_head()
        checks["migrations"] = "ok" if current == head else f"pending:{current}->{head}"
    except Exception as exc:
        checks["migrations"] = f"error:{type(exc).__name__}"
    healthy = all(value == "ok" for value in checks.values())
    if not healthy:
        _log.warning("health.not_ready checks=%s", checks)
        return error_response("NOT_READY", 503, "Service not ready", details={"checks": checks})
    return ok({"status": "ready", "checks": checks})


@blueprint.get("/info")
def info() -> Any:
    settings = resolve(Settings)
    return ok(
        {
            "service": "neotv-api",
            "version": APP_VERSION,
            "environment": settings.env,
            "modules": current_app.extensions.get("modules", {}),
        }
    )
