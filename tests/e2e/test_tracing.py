"""Tracing: one request becomes one trace across Flask, SQL and outbound HTTP.

Spans go to an in-memory exporter (synchronously), so the tests read exactly what a collector
would receive — without one.
"""

from __future__ import annotations

import pytest
import requests
from flask import Flask
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from app.kernel.observability import tracing
from app.kernel.observability.tracing import install_tracing, traces_url
from tests.support.factory import make_app

CALLER_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
CALLER_SPAN = "00f067aa0ba902b7"


@pytest.fixture
def spans() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def traced_app(spans: InMemorySpanExporter) -> Flask:
    app = make_app()
    install_tracing(app, endpoint=None, span_exporter=spans, environment="test")
    yield app
    # Leave the process untraced for other tests: requests and Celery are patched process-wide.
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    RequestsInstrumentor().uninstrument()
    CeleryInstrumentor().uninstrument()
    tracing._tracer = None


def _server(spans: InMemorySpanExporter) -> list:
    return [s for s in spans.get_finished_spans() if s.kind is SpanKind.SERVER]


def test_off_by_default_nothing_is_wrapped():
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    make_app()  # settings without OTEL_ENDPOINT
    assert tracing._tracer is None
    assert not RequestsInstrumentor().is_instrumented_by_opentelemetry


LOGIN = "/api/v1/auth/login"
WRONG = {"username": "nobody", "password": "not-a-real-password"}


def test_a_request_is_one_trace_from_route_to_sql(traced_app, spans):
    response = traced_app.test_client().post(LOGIN, json=WRONG)  # looks the user up: real SQL
    assert response.status_code == 401
    [server] = _server(spans)
    assert server.attributes["http.route"] == LOGIN
    trace_id = server.context.trace_id
    sql = [s for s in spans.get_finished_spans() if s.attributes.get("db.system")]
    assert sql, "no SQL span: SQLAlchemy is not instrumented"
    assert all(s.context.trace_id == trace_id for s in sql)  # same trace…
    [handler] = [s for s in spans.get_finished_spans() if s.name == "app.modules.identity.http.login"]
    assert handler.context.trace_id == trace_id  # …and the endpoint() handler span (@traced)
    assert handler.parent.span_id == server.context.span_id


def test_a_callers_traceparent_continues_its_trace(traced_app, spans):
    traced_app.test_client().post(LOGIN, json=WRONG, headers={"traceparent": f"00-{CALLER_TRACE}-{CALLER_SPAN}-01"})
    [server] = _server(spans)
    assert format(server.context.trace_id, "032x") == CALLER_TRACE
    assert format(server.parent.span_id, "016x") == CALLER_SPAN


def test_health_and_metrics_are_not_traced(traced_app, spans):
    client = traced_app.test_client()
    client.get("/api/v1/health/live")
    client.get("/api/v1/kernel/metrics")
    assert _server(spans) == []


def test_outbound_http_is_a_child_span_and_carries_the_trace(traced_app, spans):
    sent: dict[str, str] = {}

    class _Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **_):  # what the origin would receive
            sent.update(request.headers)
            response = requests.Response()
            response.status_code, response._content, response.url = 200, b"ok", request.url
            return response

        def close(self):
            pass

    session = requests.Session()
    session.mount("https://", _Adapter())
    with tracing._tracer.start_as_current_span("parent") as parent:
        session.get("https://origin.example/live.m3u8")
    [client] = [s for s in spans.get_finished_spans() if s.kind is SpanKind.CLIENT]
    assert client.parent.span_id == parent.get_span_context().span_id
    assert sent["traceparent"].split("-")[1] == format(parent.get_span_context().trace_id, "032x")


def test_traces_url_accepts_a_base_or_a_full_url():
    assert traces_url("http://collector:4318") == "http://collector:4318/v1/traces"
    assert traces_url("http://collector:4318/") == "http://collector:4318/v1/traces"
    assert traces_url("https://x.example/v1/traces") == "https://x.example/v1/traces"
