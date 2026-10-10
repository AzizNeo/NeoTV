"""Brute-force protection: exponential back-off per account, never a hard lock
(a hard lock lets an attacker lock out any victim — "lockout DoS")."""

from __future__ import annotations

from typing import Any, Protocol

_INCR_WITH_TTL = """
local n = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[1])
return n
"""


class LoginAttemptGuard:
    FREE_ATTEMPTS = 3
    MAX_DELAY_S = 30
    CAPTCHA_AFTER = 10

    def __init__(self, redis: Any, *, window_seconds: int = 900) -> None:
        self._redis = redis
        self._window = window_seconds
        self._incr = redis.register_script(_INCR_WITH_TTL)

    @staticmethod
    def _key(username: str) -> str:
        return f"identity:login_attempts:{username.strip().lower()}"

    def attempts(self, username: str) -> int:
        return int(self._redis.get(self._key(username)) or 0)

    def required_delay(self, username: str) -> int:
        attempts = self.attempts(username)
        if attempts < self.FREE_ATTEMPTS:
            return 0
        if self._redis.exists(f"{self._key(username)}:cooldown"):
            return int(self._redis.ttl(f"{self._key(username)}:cooldown") or 1)
        return 0

    def requires_captcha(self, username: str) -> bool:
        return self.attempts(username) >= self.CAPTCHA_AFTER

    def record_failure(self, username: str) -> int:
        attempts = int(self._incr(keys=[self._key(username)], args=[self._window]))
        if attempts >= self.FREE_ATTEMPTS:
            delay = min(2 ** (attempts - self.FREE_ATTEMPTS + 1), self.MAX_DELAY_S)
            self._redis.set(f"{self._key(username)}:cooldown", "1", ex=delay)
        return attempts

    def record_success(self, username: str) -> None:
        self._redis.delete(self._key(username), f"{self._key(username)}:cooldown")


class CaptchaVerifier(Protocol):
    def verify(self, token: str | None, *, remote_ip: str | None) -> bool: ...


class NoCaptchaVerifier:
    """Default: no captcha provider configured → a required captcha cannot be
    satisfied; the attempt window (15 min) expiring is the recovery path.
    Replace by registering another ``CaptchaVerifier`` (hCaptcha/Turnstile adapter)."""

    def verify(self, token: str | None, *, remote_ip: str | None) -> bool:
        return False
