"""Guessing protection for app credentials: an address that fails too often is refused for a while.

Per address, not per credential: a per-credential lock would let anyone who knows a username
(it is in the app's URLs) lock its owner's TV out. Passwords are random (~59 bits), so guessing
is only possible online — this caps it at a few dozen tries per address and window. Only
failures count, and a success does not reset the count (an attacker with one valid credential
cannot launder failures). While blocked, credentials are not even checked: no oracle.
"""

from __future__ import annotations

from typing import Any

_INCR_WITH_TTL = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


class XtreamAuthGuard:
    #: Generous: households share an address (CGNAT), and a TV with an old password retries.
    MAX_FAILURES = 30
    WINDOW_S = 600

    def __init__(self, redis: Any) -> None:
        self._redis = redis
        self._incr = redis.register_script(_INCR_WITH_TTL)

    @staticmethod
    def _key(ip: str) -> str:
        return f"xtream:auth_failures:{ip}"

    def blocked(self, ip: str) -> bool:
        return int(self._redis.get(self._key(ip)) or 0) >= self.MAX_FAILURES

    def record_failure(self, ip: str) -> int:
        return int(self._incr(keys=[self._key(ip)], args=[self.WINDOW_S]))
