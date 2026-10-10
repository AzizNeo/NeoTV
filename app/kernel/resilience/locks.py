"""Distributed locks (token-based; release never deletes someone else's lock)."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from redis.exceptions import LockError


class LockNotAcquiredError(RuntimeError):
    pass


class LockFactory:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def lock(self, name: str, *, ttl: float) -> Any:
        return self._redis.lock(f"lock:{name}", timeout=ttl, blocking=False, thread_local=False)

    @contextmanager
    def hold(self, name: str, *, ttl: float) -> Iterator[Any]:
        lock = self.lock(name, ttl=ttl)
        if not lock.acquire(blocking=False):
            raise LockNotAcquiredError(name)
        try:
            yield lock
        finally:
            with contextlib.suppress(LockError):  # expired or taken over — never delete a foreign lock
                lock.release()
