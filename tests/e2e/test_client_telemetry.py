"""Browser telemetry endpoint: Web Vitals and errors in, closed-set metrics and scrubbed logs out.

Public endpoint, hostile input assumed: free text never becomes a metric label, secrets never reach
a log line, and malformed or oversized batches are refused.
"""

from __future__ import annotations

import logging
import re

import pytest
from flask import Flask

from app.kernel.observability.client_telemetry import scrub

URL = "/api/v1/kernel/client-events"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXZhbHVl"


def _post(app: Flask, events: list[dict], **kw: object):
    return app.test_client().post(URL, json={"events": events}, **kw)


def _scrape(app: Flask) -> str:
    return app.test_client().get("/api/v1/kernel/metrics").get_data(as_text=True)


def _value(scrape: str, sample: str) -> float:
    match = re.search(rf"^{re.escape(sample)} (\S+)$", scrape, flags=re.M)
    return float(match[1]) if match else 0.0


def vital(name: str, value: float, rating: str = "good") -> dict:
    return {"kind": "vital", "name": name, "value": value, "rating": rating}


def error(**fields: object) -> dict:
    return {"kind": "error", "source": "error", "message": "boom", "path": "/browse", **fields}


def test_vitals_become_histograms_in_seconds_and_ratings(app):
    response = _post(app, [vital("LCP", 1800), vital("INP", 600, "poor"), vital("CLS", 0.12, "needs-improvement")])
    assert response.status_code == 204
    s = _scrape(app)
    assert _value(s, 'neotv_web_vital_seconds_sum{name="LCP"}') == 1.8
    assert _value(s, 'neotv_web_vital_seconds_bucket{le="2.5",name="LCP"}') == 1
    assert _value(s, 'neotv_web_vital_seconds_sum{name="INP"}') == 0.6
    assert _value(s, "neotv_web_vital_cls_sum") == 0.12
    assert _value(s, 'neotv_web_vital_rating_total{name="INP",rating="poor"}') == 1


def test_an_error_is_counted_and_logged_scrubbed_with_its_trace(app, caplog):
    leaky = error(
        message=f"fetch /api/v1/playback/proxy?u=aHR0c&s=SIGNATURE failed with {JWT}",
        stack="at load (https://neotv.example/assets/index.js?v=1#frag:10:5)",
        path="/title/sintel?token=SECRET#t=30",
        trace_id=TRACE,
        release="2.0.0",
    )
    with caplog.at_level(logging.WARNING, logger="client"):
        assert _post(app, [leaky]).status_code == 204
    assert _value(_scrape(app), 'neotv_client_errors_total{source="error"}') == 1
    [record] = [r for r in caplog.records if r.name == "client"]
    logged = " ".join(str(v) for v in vars(record).values())
    for secret in ("SIGNATURE", "SECRET", JWT, "aHR0c", "frag"):
        assert secret not in logged, secret
    assert record.client_path == "/title/sintel"
    assert record.client_trace_id == TRACE
    assert "[jwt]" in record.client_message


@pytest.mark.parametrize(
    "events",
    [
        [vital("FID", 10)],  # not one of ours: no free-form metric labels
        [vital("LCP", 10, "great")],
        [error(source="console")],
        [error(trace_id="not-a-trace-id")],
        [error(extra="field")],
        [vital("LCP", 10)] * 21,  # batch cap
        [],
    ],
)
def test_malformed_or_oversized_batches_are_refused(app, events):
    assert _post(app, events).status_code == 422


def test_no_free_text_ever_becomes_a_label(app):
    _post(app, [error(message="<script>label-injection</script>", path="/x" * 100)])
    assert "label-injection" not in _scrape(app)


def test_rate_limited_per_ip(app):
    statuses = [_post(app, [vital("TTFB", 100)]).status_code for _ in range(15)]
    assert statuses[:10] == [204] * 10
    assert 429 in statuses


def test_scrub_keeps_meaning_and_drops_secrets():
    assert scrub("GET /a/b?x=1&sig=2 failed", 100) == "GET /a/b failed"
    assert scrub(None, 10) is None
    assert scrub("y" * 50, 10) == "y" * 10
