"""Catch-up playback (ADR-0012): a window of an archived channel through the normal playback gate.

The recorder's output is faked as files; everything after it — policy, session, signed window,
playlist, segments — is the real path.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from flask import Flask

from app.kernel.container import resolve
from app.kernel.time import utcnow
from app.modules.live.archive import SEGMENT_SECONDS, ArchiveStorage
from tests.support.client import Api
from tests.support.factory import make_app

SESSIONS = "/api/v1/playback/sessions"


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return make_app(archive_root=tmp_path)


@pytest.fixture
def api(app: Flask) -> Api:
    return Api(app)


@pytest.fixture
def now() -> datetime:
    return utcnow().replace(microsecond=0)


def _record(app: Flask, channel_id: int, start: datetime, end: datetime) -> None:
    with app.app_context():
        storage = resolve(ArchiveStorage)
        moment = start
        while moment < end:
            path = storage.channel_dir(channel_id) / storage.segment_name(moment)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x47" * 188)  # one MPEG-TS packet
            moment += timedelta(seconds=SEGMENT_SECONDS)


def _channel(api: Api, admin: str, *, days: int = 3, rating: str = "general") -> dict[str, Any]:
    body = {"name": "Haber", "upstream_url": "https://live.example.com/a.m3u8", "rating": rating}
    channel = api.post("/api/v1/live/admin/channels", token=admin, json=body).data["channel"]
    if days:
        reply = api.put(
            f"/api/v1/live/admin/channels/{channel['id']}/archive",
            token=admin,
            json={"days": days, "rights_confirmed": True},
        )
        assert reply.status == 200, reply.body
    return dict(channel)


def _family(api: Api, name: str) -> str:
    token = api.user(name)
    assert api.post("/api/v1/billing/trial", token=token).status == 200  # trial = Family: 7 days of catch-up
    return token


def _open(api: Api, token: str, ref: str, start: datetime, end: datetime, **kw: Any) -> Any:
    window = {"start": start.isoformat(), "end": end.isoformat()}
    return api.post(SESSIONS, token=token, json={"content_ref": ref, "window": window}, **kw)


def test_a_past_window_plays_as_a_signed_vod_playlist(app: Flask, api: Api, admin: str, now: datetime) -> None:
    channel = _channel(api, admin)
    start, end = now - timedelta(minutes=30), now - timedelta(minutes=29)
    _record(app, channel["id"], start - timedelta(minutes=1), end + timedelta(minutes=1))
    viewer = _family(api, "cu1")
    opened = _open(api, viewer, channel["ref"], start, end)
    assert opened.status == 201, opened.body
    url = opened.data["manifest_url"]
    assert url.startswith(
        f"/api/v1/live/archive/{channel['id']}/{int(start.timestamp())}-{int(end.timestamp())}/index.m3u8?"
    )
    assert opened.data["is_live"] is False and "live.example.com" not in url

    playlist = api.get(url)
    assert playlist.status == 200 and playlist.headers["Content-Type"].startswith("application/vnd.apple.mpegurl")
    text = playlist.raw.decode()
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in text and text.rstrip().endswith("#EXT-X-ENDLIST")
    assert "#EXT-X-PROGRAM-DATE-TIME:" in text
    uris = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert len(uris) == 60 // SEGMENT_SECONDS  # the fake recording has a segment starting exactly at the start
    query = urlsplit(url).query
    assert all(u.endswith(f"?{query}") for u in uris)  # each segment carries the window's grant

    base = url.split("index.m3u8")[0]
    segment = api.get(base + uris[0])
    assert segment.status == 200 and segment.raw.startswith(b"\x47")


def test_the_grant_names_the_window(app: Flask, api: Api, admin: str, now: datetime) -> None:
    channel = _channel(api, admin)
    start, end = now - timedelta(minutes=30), now - timedelta(minutes=29)
    _record(app, channel["id"], start - timedelta(hours=1), end)
    url = _open(api, _family(api, "cu2"), channel["ref"], start, end).data["manifest_url"]
    path, query = url.split("?", 1)
    wider = path.replace(f"-{int(end.timestamp())}/", f"-{int(end.timestamp()) + 3600}/")
    assert api.get(f"{wider}?{query}").code == "GRANT_INVALID"  # cannot widen or move the window
    earlier = (start - timedelta(minutes=50)).strftime("%Y%m%d/%H/%Y%m%dT%H%M%SZ.ts")
    assert api.get(f"{path.rsplit('/', 1)[0]}/{earlier}?{query}").status == 404  # outside the window
    assert api.get(f"{path.rsplit('/', 1)[0]}/../../etc/passwd?{query}").status == 404
    assert api.get(path).status == 403  # no grant at all


def test_start_over_plays_a_programme_still_on_air(app: Flask, api: Api, admin: str, now: datetime) -> None:
    channel = _channel(api, admin)
    _record(app, channel["id"], now - timedelta(minutes=5), now)
    opened = _open(api, _family(api, "cu3"), channel["ref"], now - timedelta(minutes=4), now + timedelta(minutes=30))
    assert opened.status == 201 and opened.data["is_live"] is True
    text = api.get(opened.data["manifest_url"]).raw.decode()
    assert "#EXT-X-PLAYLIST-TYPE:EVENT" in text and "#EXT-X-ENDLIST" not in text  # it keeps growing


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("free plan", "CATCHUP_NOT_IN_PLAN"),
        ("not archived", "CATCHUP_NOT_AVAILABLE"),
        ("older than the channel keeps", "CATCHUP_TOO_OLD"),
        ("not started", "CATCHUP_NOT_STARTED"),
        ("not a live channel", "CATCHUP_NOT_AVAILABLE"),
    ],
)
def test_what_the_gate_refuses(api: Api, admin: str, now: datetime, case: str, code: str) -> None:
    archived, plain = _channel(api, admin, days=3), _channel(api, admin, days=0)
    viewer = api.user("cu4") if case == "free plan" else _family(api, "cu4")
    ref = {"not archived": plain["ref"], "not a live channel": api.channel(admin, "Film", kind="vod")["ref"]}.get(
        case, archived["ref"]
    )
    start = {
        "older than the channel keeps": now - timedelta(days=4),  # Family allows 7, the channel keeps 3
        "not started": now + timedelta(minutes=5),
    }.get(case, now - timedelta(hours=1))
    reply = _open(api, viewer, ref, start, start + timedelta(minutes=30))
    assert (reply.status, reply.code) == (403, code), reply.body


def test_kids_rules_and_window_validation_still_apply(api: Api, admin: str, now: datetime) -> None:
    late = _channel(api, admin, rating="adult")
    token = _family(api, "cu5")
    kids = api.post("/api/v1/profiles", token=token, json={"name": "Kids", "is_kids": True}).data
    as_kids = {
        "X-Profile-Token": api.post(f"/api/v1/profiles/{kids['id']}/select", token=token, json={}).data["profile_token"]
    }
    start = now - timedelta(hours=1)
    assert (
        _open(api, token, late["ref"], start, start + timedelta(minutes=5), headers=as_kids).code
        == "CONTENT_NOT_ALLOWED_FOR_KIDS"
    )
    assert _open(api, token, late["ref"], start, start - timedelta(minutes=1)).status == 422  # ends before it starts
    assert _open(api, token, late["ref"], start, start + timedelta(hours=7)).status == 422  # over 6 hours
