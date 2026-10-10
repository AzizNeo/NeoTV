from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
_log = logging.getLogger("resilience.best_effort")


def best_effort(fn: Callable[[], T], *, op: str, default: T | None = None) -> T | None:
    """For side effects / optimisations only: a failure never breaks the main
    flow, but it is never silent either (logged with stack trace and op name)."""
    try:
        return fn()
    except Exception:
        _log.warning("best_effort.failed op=%s", op, exc_info=True)
        return default
