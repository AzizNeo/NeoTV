"""Concurrent-stream slots in Redis (atomic Lua, heartbeat sliding window).

* ``acquire``: prune expired members, check the limit, add the token and its
  owner metadata — one atomic script (no COUNT-then-INSERT race, DATA-01).
* ``heartbeat``: only the owner can extend a slot (IDOR-safe, SEC-08).
* ``release``: by token alone (``sendBeacon`` cannot send headers); the owner
  is looked up from the token metadata.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

_ACQUIRE = """
local slots = KEYS[1]
local meta = KEYS[2]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local token = ARGV[4]
redis.call('ZREMRANGEBYSCORE', slots, '-inf', now - window)
local active = redis.call('ZCARD', slots)
if active >= limit then
  return {0, active}
end
redis.call('ZADD', slots, now, token)
redis.call('EXPIRE', slots, window * 4)
redis.call('HSET', meta, 'user_id', ARGV[5], 'device_key', ARGV[6])
redis.call('EXPIRE', meta, window * 4)
return {1, active + 1}
"""

_HEARTBEAT = """
local slots = KEYS[1]
local meta = KEYS[2]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local score = redis.call('ZSCORE', slots, ARGV[3])
if (not score) or tonumber(score) < now - window then
  return 0
end
redis.call('ZADD', slots, now, ARGV[3])
redis.call('EXPIRE', slots, window * 4)
redis.call('EXPIRE', meta, window * 4)
return 1
"""


@dataclass(frozen=True, slots=True)
class SlotOwner:
    user_id: int
    device_key: str


class StreamConcurrencyGuard:
    def __init__(self, redis: Any, *, window_seconds: int = 35) -> None:
        self._redis = redis
        self._window = window_seconds
        self._acquire = redis.register_script(_ACQUIRE)
        self._heartbeat = redis.register_script(_HEARTBEAT)

    @property
    def window(self) -> int:
        return self._window

    @staticmethod
    def _slots(user_id: int) -> str:
        return f"playback:slots:{user_id}"

    @staticmethod
    def _meta(token: str) -> str:
        return f"playback:token:{token}"

    def acquire(self, *, user_id: int, token: str, limit: int, device_key: str) -> tuple[bool, int]:
        granted, active = self._acquire(
            keys=[self._slots(user_id), self._meta(token)],
            args=[time.time(), self._window, limit, token, user_id, device_key],
        )
        return bool(int(granted)), int(active)

    def heartbeat(self, *, user_id: int, token: str) -> bool:
        return bool(
            int(
                self._heartbeat(keys=[self._slots(user_id), self._meta(token)], args=[time.time(), self._window, token])
            )
        )

    def owner(self, token: str) -> SlotOwner | None:
        data = self._redis.hgetall(self._meta(token))
        if not data:
            return None
        decoded = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in data.items()
        }
        return SlotOwner(user_id=int(decoded["user_id"]), device_key=decoded.get("device_key", ""))

    def is_active(self, token: str) -> bool:
        owner = self.owner(token)
        if owner is None:
            return False
        score = self._redis.zscore(self._slots(owner.user_id), token)
        return score is not None and float(score) >= time.time() - self._window

    def release(self, token: str) -> SlotOwner | None:
        owner = self.owner(token)
        if owner is None:
            return None
        pipe = self._redis.pipeline()
        pipe.zrem(self._slots(owner.user_id), token)
        pipe.delete(self._meta(token))
        pipe.execute()
        return owner

    def tokens(self, user_id: int) -> list[str]:
        cutoff = time.time() - self._window
        return [
            t.decode() if isinstance(t, bytes) else t
            for t in self._redis.zrangebyscore(self._slots(user_id), cutoff, "+inf")
        ]

    def active_count(self, user_id: int) -> int:
        return len(self.tokens(user_id))

    def total_active(self) -> int:
        total = 0
        for key in self._redis.scan_iter(match="playback:slots:*", count=500):
            total += int(self._redis.zcount(key, time.time() - self._window, "+inf"))
        return total
