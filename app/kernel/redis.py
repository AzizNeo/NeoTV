"""Redis client factory.

``fakeredis://<name>`` URLs give an in-process server (tests only — the
settings validator does not forbid it, but every process gets its own data).
"""

from __future__ import annotations

from typing import Any

import redis

_FAKE_SERVERS: dict[str, Any] = {}


def build_redis(url: str) -> Any:
    if url.startswith("fakeredis://"):
        import fakeredis

        name = url.removeprefix("fakeredis://") or "default"
        server = _FAKE_SERVERS.setdefault(name, fakeredis.FakeServer())
        return fakeredis.FakeRedis(server=server, decode_responses=False)
    return redis.Redis.from_url(url, health_check_interval=30, socket_timeout=5, socket_connect_timeout=3)
