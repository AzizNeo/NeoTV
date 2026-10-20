"""Exports cannot be broken by what a name contains: XML-illegal characters, quotes, line breaks."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.etree import ElementTree

from app.modules.xtream import protocol

T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)


def test_xmltv_drops_characters_xml_cannot_carry() -> None:
    channel = protocol.GuideChannel(epg_id="a\x01b", name="Bell\x07 TV", icon=None)
    body = protocol.xmltv([channel], [protocol.GuideProgramme("ab", "Tit\x00le", None, T0, T1)], language="tr")
    root = ElementTree.fromstring(body)
    assert root.find("channel").get("id") == "ab"  # type: ignore[union-attr]
    assert root.findtext("channel/display-name") == "Bell TV"
    assert root.findtext("programme/title") == "Title"
    assert root.find("programme").get("start") == "20261018120000 +0000"  # type: ignore[union-attr]


def test_m3u_keeps_one_entry_per_two_lines_whatever_the_name() -> None:
    entry = protocol.PlaylistEntry("live", "catalog:7", 'Evil"\nhttp://attacker/x.m3u8', "G\r\nroup", None)
    text = protocol.m3u([entry], server_url="https://tv.example.com", username="u", password="p")
    lines = text.splitlines()
    assert len(lines) == 3
    assert lines[1] == (
        '#EXTINF:-1 tvg-id="" tvg-name="Evil\' http://attacker/x.m3u8" tvg-logo="" group-title="G roup",'
        "Evil' http://attacker/x.m3u8"
    )
    assert lines[2] == "https://tv.example.com/live/u/p/71.m3u8"


def test_login_server_info_follows_the_public_origin() -> None:
    https = protocol.server_info("https://tv.example.com", now=T0)
    assert (https["url"], https["port"], https["https_port"], https["server_protocol"]) == (
        "tv.example.com",
        "80",
        "443",
        "https",
    )
    custom = protocol.server_info("http://box.local:8080", now=T0)
    assert (custom["port"], custom["server_protocol"], custom["time_now"]) == ("8080", "http", "2026-10-18 12:00:00")
