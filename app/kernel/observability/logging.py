"""Structured logging. JSON in staging/prod, readable text in dev.

Every record carries ``request_id`` (and ``user_id`` when known) so a single
request can be followed across API, outbox and Celery logs.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from flask import g, has_request_context

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None)))


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if has_request_context():
            record.request_id = g.get("request_id", "-")
            principal = g.get("_kernel_principal")
            record.user_id = getattr(principal, "id", None)
        else:
            record.request_id = getattr(record, "request_id", "-")
            record.user_id = getattr(record, "user_id", None)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        user_id = getattr(record, "user_id", None)
        if user_id is not None:
            payload["user_id"] = user_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(*, level: str, json_output: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s", "%H:%M:%S")
        )
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_neotv", False):
            root.removeHandler(existing)
    handler._neotv = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("werkzeug").setLevel("WARNING")
