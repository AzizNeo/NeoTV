"""OpenTelemetry tracing: one trace per request, across Flask, SQL, outbound HTTP and Celery.

Off unless ``OTEL_ENDPOINT`` is set (then nothing is imported or wrapped — PERF-04). When on:

* **Automatic spans** — Flask (incoming requests; the W3C ``traceparent`` of a caller is
  honoured, so a browser or a proxy can start the trace), SQLAlchemy (each query), ``requests``
  (every egress call: TMDB, playlist fetches, the media proxy's origin requests) and Celery
  (publish → task, the trace continues into the worker).
* ``@traced`` (used by ``endpoint()``) adds a span around each handler, under the request span.
* **Export** — OTLP over HTTP (``<OTEL_ENDPOINT>/v1/traces``, port 4318 by convention): protobuf
  only, no grpcio, passes ordinary HTTP proxies.
* **Sampling** — parent-based ratio (``OTEL_SAMPLE_RATIO``): a request is sampled whole or not at
  all, and a caller's decision is respected.
* Health and metrics endpoints are not traced (Prometheus would otherwise dominate the traces).

The tracer provider is passed explicitly to every instrumentation rather than set globally:
OpenTelemetry allows the global provider to be set once per process, and tests build many apps.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask

_tracer: Any = None
#: Paths never traced (comma-separated regexes, OpenTelemetry's excluded_urls format).
EXCLUDED_URLS = "/api/v1/health/.*,/api/v1/kernel/metrics"


class TelemetryUnavailableError(RuntimeError):
    pass


def traces_url(endpoint: str) -> str:
    """``http://collector:4318`` → ``http://collector:4318/v1/traces`` (a full URL is kept)."""
    endpoint = endpoint.rstrip("/")
    return endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"


def install_tracing(
    app: Flask,
    *,
    endpoint: str | None,
    sample_ratio: float = 1.0,
    environment: str = "dev",
    span_exporter: Any = None,
) -> None:
    """``span_exporter`` (tests) replaces the OTLP exporter and exports synchronously."""
    global _tracer  # noqa: PLW0603 - process-wide tracer for @traced, installed at boot
    if not endpoint and span_exporter is None:
        _tracer = None
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:  # pragma: no cover - the packages are in requirements.txt
        raise TelemetryUnavailableError("OTEL_ENDPOINT is set but OpenTelemetry is not installed") from exc

    from app.kernel.db import db

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "neotv-api"),
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(sample_ratio)))
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    else:
        assert endpoint
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_url(endpoint))))

    FlaskInstrumentor().instrument_app(app, tracer_provider=provider, excluded_urls=EXCLUDED_URLS)
    with app.app_context():
        SQLAlchemyInstrumentor().instrument(engine=db.engine, tracer_provider=provider)
    # requests and Celery are patched process-wide: re-instrument so this provider is the one used.
    for instrumentor in (RequestsInstrumentor(), CeleryInstrumentor()):
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()
        instrumentor.instrument(tracer_provider=provider)
    _tracer = provider.get_tracer("neotv")


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
