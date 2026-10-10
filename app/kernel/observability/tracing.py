"""Optional OpenTelemetry tracing.

Nothing happens at import time (PERF-04). Tracing is installed only when
``OTEL_ENDPOINT`` is configured; otherwise ``traced`` is a zero-cost pass-through.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

_tracer: Any = None


class TelemetryUnavailableError(RuntimeError):
    pass


def install_tracing(*, endpoint: str | None, service_name: str = "neotv-api") -> None:
    global _tracer  # noqa: PLW0603 - process-wide tracer installed once at boot
    if not endpoint:
        _tracer = None
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise TelemetryUnavailableError(
            "OTEL_ENDPOINT is set but opentelemetry packages are missing; install requirements-otel.txt"
        ) from exc
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("neotv")


def traced(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if _tracer is None:
                return fn(*args, **kwargs)
            with _tracer.start_as_current_span(name) as span:
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    raise

        return wrapper

    return decorator
