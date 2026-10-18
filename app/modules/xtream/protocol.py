"""The Xtream Codes wire format — pure functions, no Flask, no database.

Xtream apps are strict about this shape: most numbers travel as *strings* ("1", "1700000000"), flags
as "0"/"1", a few fields as real numbers (``stream_id``, ``num``, ``parent_id``, ``tv_archive``).
A value of the wrong JSON type is enough for some apps to drop a whole list, so every shape is built
here, once, and pinned by tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.shared_kernel.content import ContentRef, InvalidContentRefError

#: Content namespaces an Xtream stream id can point at → the id's last digit. Never renumber one:
#: apps store stream ids (favourites, last channel). A new namespace takes a new digit.
NAMESPACE_CODES: dict[str, int] = {"catalog": 1, "live": 2}
_CODE_NAMESPACES = {code: ns for ns, code in NAMESPACE_CODES.items()}

#: Category of NeoTV's own live channels (the live module has no groups); a brand, so no translation.
OWN_LIVE_CATEGORY = "NeoTV Live"
#: Words the protocol needs that NeoTV's data does not carry, per account language.
WORDS: dict[str, dict[str, str]] = {
    "tr": {"other": "Diğer", "season": "Sezon {n}"},
    "en": {"other": "Other", "season": "Season {n}"},
}


def word(locale: str, key: str, **values: object) -> str:
    return (WORDS.get(locale) or WORDS["tr"])[key].format(**values)


#: What every stream URL may end with (HLS only: the signed proxy serves playlists, not MPEG-TS).
OUTPUT_FORMATS = ("m3u8",)


def stream_id(ref: str) -> int:
    """``catalog:12`` → 121, ``live:3`` → 32: stable, reversible, unique across namespaces."""
    parsed = ContentRef.parse(ref)
    return parsed.id * 10 + NAMESPACE_CODES[parsed.namespace]


def content_ref(value: str | int) -> ContentRef | None:
    """The content a stream id points at, or ``None`` for anything that is not one."""
    text = str(value)
    if not text.isdigit() or len(text) > 18:
        return None
    number = int(text)
    namespace = _CODE_NAMESPACES.get(number % 10)
    try:
        return ContentRef(namespace, number // 10) if namespace else None
    except InvalidContentRefError:
        return None


def epoch(moment: datetime) -> str:
    return str(int(moment.timestamp()))


def flag(value: bool) -> str:
    return "1" if value else "0"


@dataclass(frozen=True, slots=True)
class Account:
    username: str
    password: str
    created_at: datetime
    max_connections: int
    active_connections: int


def login(account: Account, *, server_url: str, now: datetime) -> dict[str, Any]:
    """The answer to an authenticated request without ``action`` — what apps call "login"."""
    return {
        "user_info": {
            "username": account.username,
            "password": account.password,  # the app's own secret, echoed as the protocol requires
            "message": "",
            "auth": 1,
            "status": "Active",
            "exp_date": None,  # access follows the account and its plan, not a fixed end date
            "is_trial": "0",
            "active_cons": str(account.active_connections),
            "created_at": epoch(account.created_at),
            "max_connections": str(account.max_connections),
            "allowed_output_formats": list(OUTPUT_FORMATS),
        },
        "server_info": server_info(server_url, now=now),
    }


def server_info(server_url: str, *, now: datetime) -> dict[str, Any]:
    parts = urlsplit(server_url)
    https = parts.scheme == "https"
    port = parts.port or (443 if https else 80)
    return {
        "url": parts.hostname or "",
        "port": str(80 if https else port),
        "https_port": str(port if https else 443),
        "server_protocol": "https" if https else "http",
        "rtmp_port": "",
        "timezone": "UTC",
        "timestamp_now": int(now.timestamp()),
        "time_now": now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "process": True,
    }


DENIED: dict[str, Any] = {"user_info": {"auth": 0}}


def category(category_id: int, name: str) -> dict[str, Any]:
    return {"category_id": str(category_id), "category_name": name, "parent_id": 0}


def live_stream(
    *,
    num: int,
    ref: str,
    name: str,
    icon: str | None,
    category_id: int,
    epg_channel_id: str | None,
    added_at: datetime,
    adult: bool,
) -> dict[str, Any]:
    return {
        "num": num,
        "name": name,
        "stream_type": "live",
        "stream_id": stream_id(ref),
        "stream_icon": icon or "",
        "epg_channel_id": epg_channel_id,
        "added": epoch(added_at),
        "is_adult": flag(adult),
        "category_id": str(category_id),
        "category_ids": [category_id],
        "custom_sid": "",
        "tv_archive": 0,
        "direct_source": "",  # never the origin: apps must come through NeoTV's signed proxy
        "tv_archive_duration": 0,
    }


def _duration(minutes: int | None) -> tuple[int, str]:
    seconds = (minutes or 0) * 60
    return seconds, f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:00"


def _common_vod(
    *, num: int, name: str, category_id: int, category_ids: list[int], added_at: datetime
) -> dict[str, Any]:
    return {
        "num": num,
        "name": name,
        "added": epoch(added_at),
        "category_id": str(category_id),
        "category_ids": category_ids,
        # No viewer scores in NeoTV: "0", not "", so apps that parse it as a number keep the list.
        "rating": "0",
        "rating_5based": 0,
    }


def vod_stream(
    *,
    num: int,
    ref: str,
    name: str,
    icon: str | None,
    category_id: int,
    category_ids: list[int],
    added_at: datetime,
    adult: bool,
) -> dict[str, Any]:
    return {
        **_common_vod(num=num, name=name, category_id=category_id, category_ids=category_ids, added_at=added_at),
        "stream_type": "movie",
        "stream_id": stream_id(ref),
        "stream_icon": icon or "",
        "is_adult": flag(adult),
        "container_extension": OUTPUT_FORMATS[0],
        "custom_sid": "",
        "direct_source": "",
    }


def vod_info(
    *,
    ref: str,
    name: str,
    original_name: str,
    plot: str | None,
    genres: list[str],
    year: int | None,
    runtime_minutes: int | None,
    poster: str | None,
    backdrop: str | None,
    category_id: int,
    category_ids: list[int],
    added_at: datetime,
) -> dict[str, Any]:
    seconds, clock = _duration(runtime_minutes)
    return {
        "info": {
            "name": name,
            "o_name": original_name,
            "movie_image": poster or "",
            "cover_big": poster or "",
            "backdrop_path": [backdrop] if backdrop else [],
            "plot": plot or "",
            "genre": ", ".join(genres),
            "releasedate": str(year) if year else "",
            "duration_secs": seconds,
            "duration": clock,
            "rating": "0",
            "cast": "",
            "director": "",
            "youtube_trailer": "",
        },
        "movie_data": {
            "stream_id": stream_id(ref),
            "name": name,
            "added": epoch(added_at),
            "category_id": str(category_id),
            "category_ids": category_ids,
            "container_extension": OUTPUT_FORMATS[0],
            "custom_sid": "",
            "direct_source": "",
        },
    }


def series_item(
    *,
    num: int,
    series_id: int,
    name: str,
    cover: str | None,
    backdrop: str | None,
    plot: str | None,
    genres: list[str],
    year: int | None,
    runtime_minutes: int | None,
    category_id: int,
    category_ids: list[int],
    added_at: datetime,
    updated_at: datetime,
) -> dict[str, Any]:
    item = _common_vod(num=num, name=name, category_id=category_id, category_ids=category_ids, added_at=added_at)
    del item["added"]  # series carry last_modified instead
    return {
        **item,
        "series_id": series_id,
        "cover": cover or "",
        "plot": plot or "",
        "cast": "",
        "director": "",
        "genre": ", ".join(genres),
        "releaseDate": str(year) if year else "",
        "last_modified": epoch(updated_at),
        "backdrop_path": [backdrop] if backdrop else [],
        "youtube_trailer": "",
        "episode_run_time": str(runtime_minutes or 0),
    }


def episode(
    *,
    ref: str,
    season: int,
    number: int,
    title: str,
    plot: str | None,
    runtime_minutes: int | None,
    still: str | None,
    added_at: datetime,
) -> dict[str, Any]:
    seconds, clock = _duration(runtime_minutes)
    return {
        "id": str(stream_id(ref)),  # a string here, unlike everywhere else — as the protocol has it
        "episode_num": number,
        "title": title,
        "container_extension": OUTPUT_FORMATS[0],
        "info": {"duration_secs": seconds, "duration": clock, "plot": plot or "", "movie_image": still or ""},
        "custom_sid": "",
        "added": epoch(added_at),
        "season": season,
        "direct_source": "",
    }


def season(number: int, *, name: str, episode_count: int, cover: str | None) -> dict[str, Any]:
    return {
        "season_number": number,
        "name": name,
        "episode_count": str(episode_count),
        "cover": cover or "",
        "cover_big": cover or "",
        "overview": "",
        "air_date": "",
    }
