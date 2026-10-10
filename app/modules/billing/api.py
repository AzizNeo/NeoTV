"""PUBLIC surface of the billing module."""

from __future__ import annotations

from typing import Protocol

from app.modules.billing.domain import Entitlements


class EntitlementsReader(Protocol):
    """Capability ``billing.entitlements``: what the account may do *right now*."""

    def for_user(self, user_id: int) -> Entitlements: ...


class BillingReports(Protocol):
    """Capability ``billing.reports``: aggregate / per-account plan facts for back-office views."""

    def plan_distribution(self) -> dict[str, int]: ...
    def effective_plans(self, user_ids: list[int]) -> dict[int, str]: ...


__all__ = ["BillingReports", "Entitlements", "EntitlementsReader"]
