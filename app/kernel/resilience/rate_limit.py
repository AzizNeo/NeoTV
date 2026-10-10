"""GCRA (generic cell rate algorithm) rate limiting on Redis.

Atomic single Lua script, server-side clock (``TIME``), sliding precision,
burst support. ``retry_after`` is returned as a *string* because Redis
truncates Lua numbers to integers (sub-second values would become 0).
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from flask import request

GCRA_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000000 + tonumber(t[2])
local period = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local burst = tonumber(ARGV[3])
local emission = period / limit
local burst_offset = emission * burst
local tat = tonumber(redis.call('GET', KEYS[1]))
if (not tat) or tat < now then tat = now end
local new_tat = tat + emission
local allow_at = new_tat - burst_offset
if allow_at > now then
  return {0, tostring((allow_at - now) / 1000000)}
end
redis.call('SET', KEYS[1], string.format('%.0f', new_tat), 'PX', math.ceil((new_tat - now) / 1000) + 1)
return {1, '0'}
"""


@dataclass(frozen=True, slots=True)
class Rate:
    scope: str
    rps: float
    burst: int = 5
    per: Literal["user", "ip"] = "user"

    def __post_init__(self) -> None:
        if self.rps <= 0 or self.burst < 0:
            raise ValueError("rps must be > 0 and burst >= 0")


class GCRARateLimiter:
    def __init__(self, redis: Any) -> None:
        self._redis = redis
        self._script = redis.register_script(GCRA_SCRIPT)

    def allow(self, key: str, *, rps: float, burst: int) -> tuple[bool, float]:
        allowed, retry_after = self._script(keys=[f"rl:{key}"], args=[1_000_000, rps, burst])
        if isinstance(retry_after, bytes):
            retry_after = retry_after.decode()
        return bool(int(allowed)), float(retry_after)


def rate_limited(rate: Rate, identity: Callable[[], str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    from app.kernel.container import resolve
    from app.kernel.http.errors import ApiError

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            limiter = resolve(GCRARateLimiter)
            allowed, retry_after = limiter.allow(f"{rate.scope}:{identity()}", rps=rate.rps, burst=rate.burst)
            if not allowed:
                raise ApiError(
                    "RATE_LIMITED",
                    429,
                    "Too many requests",
                    details={"retry_after_seconds": round(retry_after, 3)},
                    headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def client_ip() -> str:
    return request.remote_addr or "unknown"
