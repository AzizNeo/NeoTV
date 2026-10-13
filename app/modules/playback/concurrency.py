"""Concurrent-stream slots in Redis (atomic Lua, heartbeat sliding window).

* ``acquire``: prune expired members, *replace this device's previous stream*,
  check the limit, add the token and its owner metadata — one atomic script.
  (Replacing outside the script raced: two opens from one device — React
  StrictMode, a double click, two tabs — both saw "no previous stream" and the
  second hit the limit.)
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
local owners = KEYS[3]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local token = ARGV[4]
local device = ARGV[6]
local expired = redis.call('ZRANGEBYSCORE', slots, '-inf', now - window)
redis.call('ZREMRANGEBYSCORE', slots, '-inf', now - window)
for _, t in ipairs(expired) do redis.call('HDEL', owners, t) end
-- this device's live streams are replaced by the new one (decided before anything is changed)
local replaced = {}
local pairs_ = redis.call('HGETALL', owners)
for i = 1, #pairs_, 2 do
  if pairs_[i + 1] == device and redis.call('ZSCORE', slots, pairs_[i]) then
    table.insert(replaced, pairs_[i])
  end
end
local active = redis.call('ZCARD', slots) - #replaced
if active >= limit then
  return {0, active, {}}
end
for _, t in ipairs(replaced) do
  redis.call('ZREM', slots, t)
  redis.call('HDEL', owners, t)
end
redis.call('ZADD', slots, now, token)
redis.call('EXPIRE', slots, window * 4)
redis.call('HSET', owners, token, device)
redis.call('EXPIRE', owners, window * 4)
redis.call('HSET', meta, 'user_id', ARGV[5], 'device_key', device)
redis.call('EXPIRE', meta, window * 4)
return {1, active + 1, replaced}
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
class Acquired:
    granted: bool
    active: int
    replaced: list[str]  # tokens of this device's earlier streams, ended by this acquire


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

    @staticmethod
    def _owners(user_id: int) -> str:
        return f"playback:owners:{user_id}"  # token → device_key, pruned with the slots

    def acquire(self, *, user_id: int, token: str, limit: int, device_key: str) -> Acquired:
        """Atomically: drop this device's previous stream(s), check ``limit``, take a slot."""
        granted, active, replaced = self._acquire(
            keys=[self._slots(user_id), self._meta(token), self._owners(user_id)],
            args=[time.time(), self._window, limit, token, user_id, device_key],
        )
        tokens = [t.decode() if isinstance(t, bytes) else str(t) for t in replaced or []]
        if tokens:
            self._redis.delete(*(self._meta(t) for t in tokens))
        return Acquired(granted=bool(int(granted)), active=int(active), replaced=tokens)

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
        pipe.hdel(self._owners(owner.user_id), token)
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
