"""Structured logging. JSON in staging/prod, readable text in dev.

Every record carries ``request_id`` (and ``user_id`` when known) so a single
request can be followed across API, outbox and Celery logs — and, when tracing is on and the
request is sampled, ``trace_id``/``span_id``: from a log line straight to its trace.
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
        _add_trace(record)
        return True


def _add_trace(record: logging.LogRecord) -> None:
    from app.kernel.observability import tracing

    if tracing._tracer is None:  # tracing off: nothing imported, nothing added
        return
    from opentelemetry import trace

    context = trace.get_current_span().get_span_context()
    if context.is_valid and context.trace_flags.sampled:  # only ids a trace backend will have
        record.trace_id = format(context.trace_id, "032x")
        record.span_id = format(context.span_id, "016x")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = getattr(record, "span_id", None)
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
