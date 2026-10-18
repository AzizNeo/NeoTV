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
