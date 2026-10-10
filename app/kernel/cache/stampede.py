"""Cache-stampede protection with stale-while-revalidate.

* Fresh hit → return.
* Miss → one caller wins a token-owned lock and recomputes; others get the
  *stale* copy immediately if one exists, otherwise poll briefly and give up
  with ``CacheComputeTimeoutError`` (mapped to 503) — never hold a thread for
  the full lock TTL.
* Only JSON-serialisable values are accepted (``JsonCodec``); a service that
  leaks ORM objects fails loudly at the cache boundary (RT-04), not in prod
  traffic through a cryptic TypeError.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")

_RELEASE = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"


class CacheComputeTimeoutError(RuntimeError):
    pass


class CacheSerializationError(TypeError):
    pass


class JsonCodec(Generic[T]):
    def __init__(self, encode: Callable[[T], Any] = lambda v: v, decode: Callable[[Any], T] = lambda v: v) -> None:
        self._encode = encode
        self._decode = decode

    def dumps(self, value: T) -> str:
        try:
            return json.dumps(self._encode(value), separators=(",", ":"))
        except TypeError as exc:
            raise CacheSerializationError(f"value is not JSON serialisable: {exc}") from exc

    def loads(self, raw: str | bytes) -> T:
        return self._decode(json.loads(raw))


class StampedeGuard:
    def __init__(
        self,
        redis: Any,
        *,
        namespace: str,
        ttl: int,
        stale_ttl: int,
        lock_timeout: int = 15,
        wait_budget: float = 2.0,
    ) -> None:
        self._redis = redis
        self._ns = namespace
        self._ttl = ttl
        self._stale_ttl = stale_ttl
        self._lock_timeout = lock_timeout
        self._wait_budget = wait_budget

    def get_or_compute(self, key: str, compute: Callable[[], T], codec: JsonCodec[T] | None = None) -> T:
        codec = codec or JsonCodec()
        fresh_key, stale_key, lock_key = (f"{self._ns}:{p}:{key}" for p in ("fresh", "stale", "lock"))

        cached = self._redis.get(fresh_key)
        if cached is not None:
            return codec.loads(cached)

        token = uuid.uuid4().hex
        if self._redis.set(lock_key, token, nx=True, ex=self._lock_timeout):
            try:
                value = compute()
                payload = codec.dumps(value)
                pipe = self._redis.pipeline()
                pipe.set(fresh_key, payload, ex=self._ttl)
                pipe.set(stale_key, payload, ex=self._ttl + self._stale_ttl)
                pipe.execute()
                return value
            finally:
                self._redis.eval(_RELEASE, 1, lock_key, token)

        stale = self._redis.get(stale_key)
        if stale is not None:
            return codec.loads(stale)

        deadline = time.monotonic() + self._wait_budget
        while time.monotonic() < deadline:
            time.sleep(0.05)
            cached = self._redis.get(fresh_key)
            if cached is not None:
                return codec.loads(cached)
        raise CacheComputeTimeoutError(f"{self._ns}:{key}")

    def invalidate(self, key: str) -> None:
        self._redis.delete(f"{self._ns}:fresh:{key}", f"{self._ns}:stale:{key}")
