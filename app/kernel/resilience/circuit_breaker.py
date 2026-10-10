"""Thread-safe circuit breaker with a correct half-open state machine.

* CLOSED  → counts consecutive *counted* failures; at threshold → OPEN.
* OPEN    → rejects with CircuitOpenError until recovery_timeout elapses.
* HALF_OPEN → admits at most ``half_open_max_calls`` concurrent probes;
  one probe failure re-opens immediately, one success closes.
* Exceptions outside ``counted`` (e.g. validation errors) do not trip it.
* Fallback is the caller's responsibility (``except CircuitOpenError``), so the
  degraded path is typed and explicit — the breaker never returns ``None``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    def __init__(self, name: str, retry_in: float) -> None:
        super().__init__(f"circuit '{name}' is open; retry in {retry_in:.1f}s")
        self.name = name
        self.retry_in = retry_in


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        counted: tuple[type[BaseException], ...] = (Exception,),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or half_open_max_calls < 1:
            raise ValueError("thresholds must be >= 1")
        self.name = name
        self._threshold = failure_threshold
        self._recovery = recovery_timeout
        self._probe_cap = half_open_max_calls
        self._counted = counted
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._in_flight_probes = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state is CircuitState.OPEN and self._clock() - self._opened_at >= self._recovery:
                return CircuitState.HALF_OPEN
            return self._state

    def call(self, fn: Callable[[], T]) -> T:
        probe = self._acquire()
        try:
            result = fn()
        except self._counted:
            self._record_failure(probe)
            raise
        except BaseException:
            self._release_probe(probe)
            raise
        self._record_success(probe)
        return result

    def reset(self) -> None:
        with self._lock:
            self._state, self._failures, self._in_flight_probes = CircuitState.CLOSED, 0, 0

    # ── state machine ──────────────────────────────────────────────────────
    def _acquire(self) -> bool:
        with self._lock:
            if self._state is CircuitState.OPEN:
                elapsed = self._clock() - self._opened_at
                if elapsed < self._recovery:
                    raise CircuitOpenError(self.name, self._recovery - elapsed)
                self._state = CircuitState.HALF_OPEN
                self._in_flight_probes = 0
            if self._state is CircuitState.HALF_OPEN:
                if self._in_flight_probes >= self._probe_cap:
                    raise CircuitOpenError(self.name, 0.0)
                self._in_flight_probes += 1
                return True
            return False

    def _release_probe(self, probe: bool) -> None:
        if probe:
            with self._lock:
                self._in_flight_probes = max(0, self._in_flight_probes - 1)

    def _record_success(self, probe: bool) -> None:
        with self._lock:
            if probe:
                self._in_flight_probes = max(0, self._in_flight_probes - 1)
            self._state = CircuitState.CLOSED
            self._failures = 0

    def _record_failure(self, probe: bool) -> None:
        with self._lock:
            if probe:
                self._in_flight_probes = max(0, self._in_flight_probes - 1)
            self._failures += 1
            if probe or self._failures >= self._threshold:
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()


class CircuitBreakerRegistry:
    """Named breakers, one per external dependency (failure domains never mix)."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, name: str, **options: Any) -> CircuitBreaker:
        with self._lock:
            breaker = self._breakers.get(name)
            if breaker is None:
                breaker = CircuitBreaker(name, **options)
                self._breakers[name] = breaker
            return breaker

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {name: b.state.value for name, b in sorted(self._breakers.items())}
