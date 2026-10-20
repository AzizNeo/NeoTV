"""Catch-up in Xtream apps (ADR-0011 + ADR-0012): archive flags, has_archive, M3U catch-up and
/timeshift URLs — through the same catch-up policy as the web player."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from app.kernel.container import resolve
from app.kernel.time import utcnow
from app.modules.live.archive import SEGMENT_SECONDS, ArchiveStorage
from app.modules.xtream.protocol import stream_id, timeshift_window
from tests.support.client import Api
from tests.support.factory import make_app

BASE = "/api/v1/xtream"


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return make_app(archive_root=tmp_path)


@pytest.fixture
def api(app: Flask) -> Api:
    return Api(app)


@pytest.fixture
def now() -> datetime:
    return utcnow().replace(second=0, microsecond=0)


@pytest.fixture
def channel(app: Flask, api: Api, admin: str, now: datetime) -> dict[str, Any]:
    body = {"name": "Haber", "upstream_url": "https://live.example.com/a.m3u8", "rating": "general"}
    created = api.post("/api/v1/live/admin/channels", token=admin, json=body).data["channel"]
    api.put(
        f"/api/v1/live/admin/channels/{created['id']}/archive", token=admin, json={"days": 3, "rights_confirmed": True}
    )
    for title, start, minutes in (
        ("İki gün önce", now - timedelta(days=2), 60),
        ("Sabah", now - timedelta(hours=2), 60),
        ("Şimdi", now - timedelta(minutes=30), 60),
        ("Akşam", now + timedelta(hours=2), 60),
    ):
        program = {
            "channel_id": created["id"],
            "title": title,
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(minutes=minutes)).isoformat(),
        }
        assert api.post("/api/v1/live/admin/epg", token=admin, json=program).status == 201
    with app.app_context():  # the recorder's output for the last three hours
        storage = resolve(ArchiveStorage)
        moment = now - timedelta(hours=3)
        while moment < now:
            path = storage.channel_dir(created["id"]) / storage.segment_name(moment)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x47" * 188)
            moment += timedelta(seconds=SEGMENT_SECONDS)
    return dict(created)


def _credential(api: Api, token: str) -> tuple[str, str]:
    profile = api.get("/api/v1/profiles", token=token).data[0]["id"]
    issued = api.post(f"{BASE}/credentials", token=token, json={"label": "TV", "profile_id": profile}).data
    return issued["credential"]["username"], issued["password"]


def _family(api: Api, name: str) -> tuple[str, str]:
    token = api.user(name)
    assert api.post("/api/v1/billing/trial", token=token).status == 200  # Family: 7 days, the channel keeps 3
    return _credential(api, token)


def _q(creds: tuple[str, str], **params: str) -> dict[str, str]:
    return {"username": creds[0], "password": creds[1], **params}


def test_lists_say_what_this_account_can_watch_back(api: Api, channel: dict[str, Any], now: datetime) -> None:
    family, free = _family(api, "xc1"), _credential(api, api.user("xc2"))
    streams = {
        s["name"]: s for s in api.get(f"{BASE}/player_api.php", query_string=_q(family, action="get_live_streams")).body
    }
    assert (streams["Haber"]["tv_archive"], streams["Haber"]["tv_archive_duration"]) == (1, 3)  # min(channel 3, plan 7)
    free_streams = {
        s["name"]: s for s in api.get(f"{BASE}/player_api.php", query_string=_q(free, action="get_live_streams")).body
    }
    assert (free_streams["Haber"]["tv_archive"], free_streams["Haber"]["tv_archive_duration"]) == (0, 0)

    sid = str(stream_id(channel["ref"]))
    table = api.get(
        f"{BASE}/player_api.php", query_string=_q(family, action="get_simple_data_table", stream_id=sid)
    ).body
    flags = {base64.b64decode(i["title"]).decode(): i["has_archive"] for i in table["epg_listings"]}
    assert flags == {"İki gün önce": 1, "Sabah": 1, "Şimdi": 1, "Akşam": 0}  # the table reaches back 3 days

    m3u = api.get(f"{BASE}/get.php", query_string=_q(family)).raw.decode()
    line = next(line for line in m3u.splitlines() if line.endswith(",Haber"))
    assert 'catchup="xc"' in line and 'catchup-days="3"' in line


def test_timeshift_opens_the_archive_window(api: Api, channel: dict[str, Any], now: datetime) -> None:
    user, password = _family(api, "xc3")
    sid = stream_id(channel["ref"])
    start = now - timedelta(hours=2)
    reply = api.get(f"{BASE}/timeshift/{user}/{password}/30/{start:%Y-%m-%d:%H-%M}/{sid}.m3u8")
    assert reply.status == 302, reply.raw
    location = reply.headers["Location"]
    window = f"{int(start.timestamp())}-{int((start + timedelta(minutes=30)).timestamp())}"
    assert location.startswith(f"http://localhost:5173/api/v1/live/archive/{channel['id']}/{window}/index.m3u8?")
    playlist = api.get(location.removeprefix("http://localhost:5173"))
    assert playlist.status == 200 and playlist.raw.decode().rstrip().endswith("#EXT-X-ENDLIST")

    query = api.get(
        f"{BASE}/streaming/timeshift.php",
        query_string=_q((user, password), stream=str(sid), start=f"{start:%Y-%m-%d:%H-%M}", duration="30"),
    )
    assert query.status == 302 and f"/{window}/index.m3u8?" in query.headers["Location"]


def test_timeshift_refusals(api: Api, channel: dict[str, Any], now: datetime) -> None:
    family, free = _family(api, "xc4"), _credential(api, api.user("xc5"))
    sid = stream_id(channel["ref"])

    def shift(creds: tuple[str, str], start: datetime, minutes: str = "30") -> Any:
        return api.get(f"{BASE}/timeshift/{creds[0]}/{creds[1]}/{minutes}/{start:%Y-%m-%d:%H-%M}/{sid}.m3u8")

    assert (shift(free, now - timedelta(hours=1)).status, shift(free, now - timedelta(hours=1)).raw) == (
        403,
        b"CATCHUP_NOT_IN_PLAN",
    )
    assert shift(family, now - timedelta(days=4)).raw == b"CATCHUP_TOO_OLD"
    assert shift(family, now + timedelta(hours=1)).raw == b"CATCHUP_NOT_STARTED"
    assert (shift(family, now, minutes="0").status, shift(family, now, minutes="999").status) == (400, 400)
    bad = api.get(f"{BASE}/timeshift/{family[0]}/{family[1]}/30/yesterday/{sid}.m3u8")
    assert (bad.status, bad.raw) == (400, b"INVALID_TIMESHIFT")
    assert api.get(f"{BASE}/timeshift/{family[0]}/{'z' * 12}/30/{now:%Y-%m-%d:%H-%M}/{sid}.m3u8").status == 401


def test_the_timeshift_start_format() -> None:
    begin, end = timeshift_window("2026-10-20:18-05", "45") or (None, None)
    assert begin is not None and begin.isoformat() == "2026-10-20T18:05:00+00:00"
    assert end is not None and (end - begin) == timedelta(minutes=45)
    for start, minutes in (
        ("2026-13-01:00-00", "5"),
        ("2026-10-20 18:05", "5"),
        ("2026-10-20:18-05", "-5"),
        ("2026-10-20:18-05", ""),
    ):
        assert timeshift_window(start, minutes) is None
