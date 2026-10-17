"""Viewer-experience metrics: startup time, watch/stall time, proxy failures.

The player sends one QoE report per session when it closes. Every report is stored (unchanged
contract), but only a *trusted* one feeds the metrics — the session is the caller's and it is its
first report — and no session can claim more playing or stalling than it existed. Otherwise any
viewer could skew the dashboards the operator alerts on.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from flask import Flask

from app.kernel.observability.metrics import Metrics
from app.kernel.security.egress import EgressDeniedError, EgressNetworkError
from app.kernel.time import Clock, FrozenClock
from app.modules.playback.api import MediaGrant
from app.modules.playback.hls_proxy import HlsProxyService, UpstreamStatusError, UpstreamUnavailableError
from tests.support.client import Api

QOE = "/api/v1/playback/qoe"


@pytest.fixture
def clock(app: Flask) -> FrozenClock:
    frozen = FrozenClock()
    app.extensions["container"].override(Clock, frozen)  # before any service is built
    return frozen


def _scrape(app: Flask) -> str:
    return app.test_client().get("/api/v1/kernel/metrics").get_data(as_text=True)


def _value(scrape: str, sample: str) -> float:
    match = re.search(rf"^{re.escape(sample)} (\S+)$", scrape, flags=re.M)
    return float(match[1]) if match else 0.0


def _session(api: Api, admin: str, viewer: str) -> tuple[str, str]:
    ref = api.channel(admin, "QoE TV")["ref"]
    opened = api.open_session(viewer, ref)
    assert opened.status == 201
    return ref, opened.data["session_token"]


def _report(api: Api, user: str, ref: str, token: str | None, **fields: object) -> None:
    body = {"content_ref": ref, "session_token": token, "device_type": "tv", **fields}
    assert api.post(QOE, token=user, json=body).status == 201  # always stored


def test_a_trusted_report_feeds_startup_watch_and_stalls(app, api, admin, viewer, clock):
    ref, token = _session(api, admin, viewer)
    clock.advance(seconds=120)
    _report(
        api, viewer, ref, token, startup_time_ms=1500, watch_duration_s=100, rebuffer_duration_ms=4000, rebuffer_count=2
    )
    s = _scrape(app)
    assert _value(s, 'neotv_playback_startup_seconds_count{device="tv"}') == 1
    assert _value(s, 'neotv_playback_startup_seconds_sum{device="tv"}') == 1.5
    assert _value(s, 'neotv_playback_startup_seconds_bucket{device="tv",le="2.0"}') == 1
    assert _value(s, 'neotv_playback_startup_seconds_bucket{device="tv",le="1.0"}') == 0
    assert _value(s, 'neotv_playback_watch_seconds_total{device="tv"}') == 100
    assert _value(s, 'neotv_playback_rebuffer_seconds_total{device="tv"}') == 4
    assert _value(s, 'neotv_playback_rebuffer_events_total{device="tv"}') == 2


def test_a_second_report_for_the_same_session_is_stored_but_not_counted(app, api, admin, viewer, clock):
    ref, token = _session(api, admin, viewer)
    clock.advance(seconds=600)
    _report(api, viewer, ref, token, watch_duration_s=100)
    _report(api, viewer, ref, token, watch_duration_s=100)
    assert _value(_scrape(app), 'neotv_playback_watch_seconds_total{device="tv"}') == 100


def test_reports_without_or_with_someone_elses_session_are_not_counted(app, api, admin, viewer, clock):
    ref, token = _session(api, admin, viewer)
    clock.advance(seconds=600)
    intruder = api.user("intruder")
    _report(api, intruder, ref, token, watch_duration_s=500)  # not the intruder's session
    _report(api, viewer, ref, None, watch_duration_s=500)  # no session at all
    assert _value(_scrape(app), 'neotv_playback_watch_seconds_total{device="tv"}') == 0


def test_no_session_claims_more_than_it_lasted(app, api, admin, viewer, clock):
    ref, token = _session(api, admin, viewer)
    clock.advance(seconds=30)
    _report(api, viewer, ref, token, watch_duration_s=36_000, rebuffer_duration_ms=9_000_000)
    s = _scrape(app)
    assert _value(s, 'neotv_playback_watch_seconds_total{device="tv"}') == 35  # 30 s lived + 5 s slack
    assert _value(s, 'neotv_playback_rebuffer_seconds_total{device="tv"}') == 35


def test_device_labels_are_a_closed_set(app, api, admin, viewer, clock):
    ref, token = _session(api, admin, viewer)
    clock.advance(seconds=60)
    _report(api, viewer, ref, token, device_type="my-fridge-9000", watch_duration_s=10)
    s = _scrape(app)
    assert _value(s, 'neotv_playback_watch_seconds_total{device="other"}') == 10
    assert "my-fridge-9000" not in s


# ── Media proxy failures ────────────────────────────────────────────────────
class _Egress:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    def get(self, url: str, **_: object) -> object:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


@pytest.mark.parametrize(
    ("outcome", "reason", "error"),
    [
        (EgressNetworkError("slow", kind="timeout"), "timeout", UpstreamUnavailableError),
        (EgressNetworkError("odd", kind="weird-new-kind"), "other", UpstreamUnavailableError),
        (EgressDeniedError("private_ip", "http://10.0.0.1/x.m3u8"), "blocked", UpstreamUnavailableError),
        (SimpleNamespace(status_code=503, close=lambda: None), "http_5xx", UpstreamStatusError),
        (SimpleNamespace(status_code=404, close=lambda: None), "http_4xx", UpstreamStatusError),
    ],
)
def test_proxy_failures_are_counted_by_cause_never_by_host(outcome, reason, error):
    metrics = Metrics()
    proxy = HlsProxyService(_Egress(outcome), urls=None, metrics=metrics)  # type: ignore[arg-type]
    grant = MediaGrant(user_id=1, session_token="t", target="https://origin.example/secret-path/x.m3u8", expires_at=0)
    with pytest.raises(error):
        proxy.fetch(grant)
    scrape = metrics.render().decode()
    assert _value(scrape, f'neotv_playback_proxy_errors_total{{reason="{reason}"}}') == 1
    assert "origin.example" not in scrape and "secret-path" not in scrape
