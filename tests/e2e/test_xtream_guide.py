"""Xtream guide and playlist: get_short_epg, get_simple_data_table, xmltv.php, get.php.

Only NeoTV's own live channels have a guide; it is served for exactly the channels the credential
may watch, in the same ids the lists use, and the exports are built so channel names can never
break the file's structure.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.etree import ElementTree

import pytest

from app.modules.xtream.protocol import own_epg_id, stream_id
from tests.support.client import Api, Reply

BASE = "/api/v1/xtream"  # nginx serves these at <server>/player_api.php, /xmltv.php, /get.php


def _credential(api: Api, token: str, profile_id: int | None = None) -> tuple[str, str]:
    profile_id = profile_id or api.get("/api/v1/profiles", token=token).data[0]["id"]
    issued = api.post(f"{BASE}/credentials", token=token, json={"label": "TV", "profile_id": profile_id}).data
    return issued["credential"]["username"], issued["password"]


def _get(api: Api, path: str, creds: tuple[str, str], **params: str) -> Reply:
    return api.get(f"{BASE}/{path}", query_string={"username": creds[0], "password": creds[1], **params})


def _own(api: Api, admin: str, name: str, rating: str = "general", epg_id: str | None = None) -> dict[str, Any]:
    body = {"name": name, "source_type": "external", "upstream_url": "https://live.example.com/x.m3u8"}
    body |= {"rating": rating, **({"epg_channel_id": epg_id} if epg_id else {})}
    reply = api.post("/api/v1/live/admin/channels", token=admin, json=body)
    assert reply.status == 201, reply.body
    return dict(reply.data["channel"])


def _programme(api: Api, admin: str, channel_id: int, title: str, start: datetime, minutes: int = 60) -> None:
    body = {
        "channel_id": channel_id,
        "title": title,
        "description": f"{title} hakkında",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(minutes=minutes)).isoformat(),
    }
    assert api.post("/api/v1/live/admin/epg", token=admin, json=body).status == 201


@pytest.fixture
def guide(api: Api, admin: str) -> dict[str, Any]:
    # "Öğle" is on air from 30 minutes ago to 30 minutes from now: no test can straddle a boundary.
    base = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=90)
    news = _own(api, admin, 'Haber <24> & "Canlı"', epg_id="haber24.tr")
    late = _own(api, admin, "Gece", rating="adult")
    plain = api.channel(admin, "Catalogue One", group="Ulusal", kind="live")
    for n, title in enumerate(["Sabah", "Öğle", "Akşam", "Gece Haberi", "Spor", "Hava"]):
        _programme(api, admin, news["id"], title, base + timedelta(hours=n))
    _programme(api, admin, late["id"], "Gece Kuşu", base + timedelta(hours=1))
    _programme(api, admin, news["id"], "Çok eski", base - timedelta(days=2))
    return {"news": news, "late": late, "plain": plain}


def _decode(item: dict[str, Any]) -> str:
    return base64.b64decode(item["title"]).decode()


def test_short_epg_starts_with_what_is_on_and_honours_the_limit(api: Api, guide: dict[str, Any]) -> None:
    creds = _credential(api, api.user("epg1"))
    news = str(stream_id(guide["news"]["ref"]))
    listings = _get(api, "player_api.php", creds, action="get_short_epg", stream_id=news).body["epg_listings"]
    assert [_decode(i) for i in listings] == ["Öğle", "Akşam", "Gece Haberi", "Spor"]  # default limit 4, from now
    first = listings[0]
    assert set(first) == {
        "id", "epg_id", "title", "lang", "start", "end", "description", "channel_id",
        "start_timestamp", "stop_timestamp", "stream_id",
    }  # fmt: skip
    assert first["epg_id"] == first["channel_id"] == "haber24.tr" and first["stream_id"] == news
    assert base64.b64decode(first["description"]).decode() == "Öğle hakkında"
    assert first["start_timestamp"].isdigit() and len(first["start"]) == 19

    two = _get(api, "player_api.php", creds, action="get_short_epg", stream_id=news, limit="2").body
    assert len(two["epg_listings"]) == 2
    for junk in ("", "x", "121", str(stream_id(guide["plain"]["ref"]))):  # a catalogue channel has no guide
        reply = _get(api, "player_api.php", creds, action="get_short_epg", stream_id=junk)
        assert reply.body == {"epg_listings": []}, junk


def test_simple_data_table_marks_what_is_on_air(api: Api, guide: dict[str, Any]) -> None:
    creds = _credential(api, api.user("epg2"))
    news = str(stream_id(guide["news"]["ref"]))
    listings = _get(api, "player_api.php", creds, action="get_simple_data_table", stream_id=news).body["epg_listings"]
    titles = [_decode(i) for i in listings]
    assert titles[:2] == ["Sabah", "Öğle"] and "Çok eski" not in titles  # 6 hours back, days ahead
    assert [i["now_playing"] for i in listings].count(1) == 1 and listings[1]["now_playing"] == 1
    assert all(i["has_archive"] == 0 for i in listings)


def test_xmltv_is_well_formed_and_matches_the_lists(api: Api, guide: dict[str, Any]) -> None:
    creds = _credential(api, api.user("epg3"))
    reply = _get(api, "xmltv.php", creds)
    assert reply.status == 200 and reply.headers["Content-Type"].startswith("application/xml")
    assert reply.headers["Cache-Control"] == "no-store"
    root = ElementTree.fromstring(reply.raw)  # parses: the name with < & " is escaped, not injected
    channels = {c.get("id"): c.findtext("display-name") for c in root.iter("channel")}
    assert channels == {"haber24.tr": 'Haber <24> & "Canlı"', own_epg_id(guide["late"]["ref"]): "Gece"}
    news_titles = [p.findtext("title") for p in root.iter("programme") if p.get("channel") == "haber24.tr"]
    assert news_titles[:2] == ["Sabah", "Öğle"] and "Çok eski" not in news_titles
    assert next(root.iter("programme")).get("start", "").endswith(" +0000")

    streams = _get(api, "player_api.php", creds, action="get_live_streams").body
    epg_ids = {s["name"]: s["epg_channel_id"] for s in streams}
    assert epg_ids["Gece"] == own_epg_id(guide["late"]["ref"]) and epg_ids["Catalogue One"] is None


def test_kids_credentials_get_the_kids_guide_only(api: Api, guide: dict[str, Any]) -> None:
    token = api.user("epg4")
    assert api.post("/api/v1/billing/trial", token=token).status == 200
    kids = api.post("/api/v1/profiles", token=token, json={"name": "Kids", "is_kids": True}).data
    creds = _credential(api, token, kids["id"])
    late = str(stream_id(guide["late"]["ref"]))
    reply = _get(api, "player_api.php", creds, action="get_short_epg", stream_id=late)
    assert reply.body == {"epg_listings": []}
    root = ElementTree.fromstring(_get(api, "xmltv.php", creds).raw)
    assert [c.get("id") for c in root.iter("channel")] == ["haber24.tr"]


def test_m3u_lists_everything_playable_with_hls_urls(api: Api, admin: str, guide: dict[str, Any]) -> None:
    film = api.channel(admin, "Film src", kind="vod")
    episode = api.channel(admin, "Ep src", kind="vod")
    for slug, doc in {
        "film": {"kind": "movie", "name": "Bir Film", "play_ref": film["ref"], "rating": "general"},
        "dizi": {
            "kind": "series",
            "name": "Dizi",
            "rating": "general",
            "seasons": [{"number": 1, "episodes": [{"number": 3, "name": "Üç", "play_ref": episode["ref"]}]}],
        },
    }.items():
        assert api.put(f"/api/v1/titles/admin/titles/{slug}", token=admin, json=doc).status == 201
    creds = _credential(api, api.user("m3u1"))
    reply = _get(api, "get.php", creds, type="m3u_plus", output="m3u8")
    assert reply.status == 200 and reply.headers["Content-Type"].startswith("audio/x-mpegurl")
    text = reply.raw.decode()
    lines = text.splitlines()
    assert lines[0].startswith('#EXTM3U url-tvg="http://localhost:5173/xmltv.php?username=')
    assert len(lines) == 1 + 2 * 5  # 3 live (2 own + 1 catalogue), 1 movie, 1 episode
    extinf = [line for line in lines if line.startswith("#EXTINF")]
    urls = [line for line in lines[1:] if not line.startswith("#")]
    assert all(line.count("\n") == 0 for line in extinf)
    assert any("tvg-name=\"Haber <24> & 'Canlı'\"" in line for line in extinf)  # a quote cannot end the attribute
    user, password = creds
    assert f"http://localhost:5173/live/{user}/{password}/{stream_id(guide['news']['ref'])}.m3u8" in urls
    assert f"http://localhost:5173/movie/{user}/{password}/{stream_id(film['ref'])}.m3u8" in urls
    assert f"http://localhost:5173/series/{user}/{password}/{stream_id(episode['ref'])}.m3u8" in urls
    assert any(line.endswith(",Dizi S01E03") for line in extinf)
    assert "live.example.com" not in text and "cdn.example.com" not in text


@pytest.mark.parametrize("path", ["xmltv.php", "get.php"])
def test_exports_refuse_wrong_credentials(api: Api, path: str) -> None:
    username, _ = _credential(api, api.user(f"x{path[:3]}"))
    reply = _get(api, path, (username, "y" * 12))
    assert (reply.status, reply.raw) == (401, b"")
