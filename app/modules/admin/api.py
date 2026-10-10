"""PUBLIC surface of the admin module.

Extension point ``admin.abuse_rules`` (declared by admin): any module may
contribute an :class:`AbuseRule`; findings are merged into reviewable flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

POINT_ABUSE_RULES = "admin.abuse_rules"


@dataclass(frozen=True, slots=True)
class AbuseFinding:
    user_id: int
    kind: str  # stable machine name, e.g. "many_ips"
    score: int  # higher = more suspicious (rule specific scale)
    details: str


class AbuseRule(Protocol):
    name: str

    def evaluate(self, now: datetime) -> list[AbuseFinding]: ...


__all__ = ["POINT_ABUSE_RULES", "AbuseFinding", "AbuseRule"]
