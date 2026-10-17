"""State metrics read at scrape time: outbox lag, dead letters, active streams.

Scraped through the real endpoint, the way Prometheus sees them. The outbox gauges existed before
but were never set (always 0: a dashboard that says "fine" whatever happens) — these tests pin
that they now follow the database, and that a failing read never breaks the scrape.
"""

from __future__ import annotations

import re
from datetime import timedelta

from flask import Flask

from app.kernel.db import db
from app.kernel.outbox.models import DeadLetter, OutboxRecord, OutboxStatus
from app.kernel.outbox.repository import OutboxRepository
from app.kernel.time import utcnow
from tests.support.client import Api

METRICS = "/api/v1/kernel/metrics"


def _scrape(app: Flask) -> str:
    response = app.test_client().get(METRICS)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _value(scrape: str, name: str) -> float:
    match = re.search(rf"^{re.escape(name)} (\S+)$", scrape, flags=re.M)
    assert match, f"{name} missing"
    return float(match[1])


def test_a_quiet_system_reads_zero(app: Flask) -> None:
    scrape = _scrape(app)
    assert _value(scrape, "neotv_outbox_lag_seconds") == 0
    assert _value(scrape, "neotv_outbox_dead_letters") == 0
    assert _value(scrape, "neotv_playback_active_streams") == 0


def test_outbox_lag_and_dead_letters_follow_the_database(app: Flask) -> None:
    with app.app_context():
        db.session.add_all(
            [
                OutboxRecord(
                    event_name="e", event_version=1, payload_json="{}", created_at=utcnow() - timedelta(minutes=2)
                ),
                OutboxRecord(  # delivered long ago: must not count
                    event_name="e",
                    event_version=1,
                    payload_json="{}",
                    status=OutboxStatus.DISPATCHED,
                    created_at=utcnow() - timedelta(hours=5),
                ),
                DeadLetter(event_id="x", consumer="c", error="boom"),
                DeadLetter(event_id="y", consumer="c", error="fixed", resolved_at=utcnow()),
            ]
        )
        db.session.commit()
    scrape = _scrape(app)
    assert 119 <= _value(scrape, "neotv_outbox_lag_seconds") < 180
    assert _value(scrape, "neotv_outbox_dead_letters") == 1


def test_active_streams_count_open_sessions(app: Flask, api: Api, admin: str, viewer: str) -> None:
    ref = api.channel(admin, "Metrics TV")["ref"]
    assert api.open_session(viewer, ref).status == 201
    assert _value(_scrape(app), "neotv_playback_active_streams") == 1


def test_a_failing_read_never_breaks_the_scrape(app: Flask, monkeypatch) -> None:
    def broken(self: OutboxRepository) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(OutboxRepository, "oldest_undelivered_at", broken)
    scrape = _scrape(app)  # still 200, still the other metrics
    assert "neotv_http_requests_total" in scrape
