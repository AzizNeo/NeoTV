"""Transcode orchestration with Redis leases (STR-02).

* ``ensure_running`` — one atomic Lua decision: only the first viewer of an
  idle stream dispatches a transcode task; everybody else just refreshes the
  ``last_viewer_at`` lease.
* The worker that owns the FFmpeg process polls its own lease every second
  and stops the process when (a) no viewer touched the stream for
  ``idle_grace`` seconds, or (b) an operator requested STOP — no cross-host
  ``killpg`` needed, and no zombie can outlive its lease.
"""

from __future__ import annotations

import time
from typing import Any

_ENSURE = """
local key = KEYS[1]
local now = ARGV[1]
local status = redis.call('HGET', key, 'status')
if status == 'STARTING' or status == 'RUNNING' then
  redis.call('HSET', key, 'last_viewer_at', now)
  return 0
end
redis.call('HSET', key, 'status', 'STARTING', 'last_viewer_at', now, 'source', ARGV[2], 'requested_at', now)
redis.call('EXPIRE', key, tonumber(ARGV[3]))
return 1
"""

PREFIX = "live:transcode:"


class TranscodeOrchestrator:
    def __init__(self, redis: Any, *, idle_grace_s: int, start_timeout_s: int = 60) -> None:
        self._redis = redis
        self._idle_grace = idle_grace_s
        self._start_timeout = start_timeout_s
        self._ensure = redis.register_script(_ENSURE)

    @staticmethod
    def key(stream_id: str) -> str:
        return f"{PREFIX}{stream_id}"

    def ensure_running(self, stream_id: str, source_url: str, dispatch: Any) -> bool:
        started = bool(
            int(self._ensure(keys=[self.key(stream_id)], args=[time.time(), source_url, self._start_timeout]))
        )
        if started:
            try:
                dispatch(stream_id, source_url)
            except Exception:
                self._redis.delete(self.key(stream_id))
                raise
        return started

    def touch(self, stream_id: str) -> None:
        if self._redis.exists(self.key(stream_id)):
            self._redis.hset(self.key(stream_id), "last_viewer_at", time.time())

    def mark_running(self, stream_id: str, *, worker: str, pid: int) -> None:
        key = self.key(stream_id)
        self._redis.hset(
            key, mapping={"status": "RUNNING", "worker": worker, "pid": pid, "last_viewer_at": time.time()}
        )
        self._redis.persist(key)

    def should_stop(self, stream_id: str) -> bool:
        data = self._redis.hgetall(self.key(stream_id))
        if not data:
            return True
        decoded = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in data.items()
        }
        if decoded.get("status") == "STOPPING":
            return True
        last = float(decoded.get("last_viewer_at", 0) or 0)
        return time.time() - last > self._idle_grace

    def request_stop(self, stream_id: str) -> None:
        if self._redis.exists(self.key(stream_id)):
            self._redis.hset(self.key(stream_id), "status", "STOPPING")

    def clear(self, stream_id: str) -> None:
        self._redis.delete(self.key(stream_id))

    def status(self, stream_id: str) -> str | None:
        raw = self._redis.hget(self.key(stream_id), "status")
        return raw.decode() if isinstance(raw, bytes) else raw

    def running_count(self) -> int:
        return sum(1 for _ in self._redis.scan_iter(match=f"{PREFIX}*", count=200))
