"""Billing domain: plans, entitlements, subscription state machine (pure Python)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class PlanId(StrEnum):
    FREE = "free"
    PERSONAL = "personal"
    DUO = "duo"
    FAMILY = "family"


@dataclass(frozen=True, slots=True)
class Entitlements:
    max_streams: int
    max_profiles: int
    max_resolution: str
    offline_downloads: bool
    ads: bool
    catchup_days: int = 0  # how far back archived live channels can be watched (ADR-0012)


@dataclass(frozen=True, slots=True)
class Plan:
    id: PlanId
    display_name: str
    price_minor: int  # kuruş — never floats for money
    currency: str
    cycle: str
    features: tuple[str, ...]
    entitlements: Entitlements

    @property
    def is_paid(self) -> bool:
        return self.price_minor > 0


class UnknownPlanError(LookupError):
    pass


class PlanCatalog:
    def __init__(self, plans: list[Plan]) -> None:
        ids = [p.id for p in plans]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate plan id in catalogue")
        if PlanId.FREE not in ids:
            raise ValueError("catalogue must contain the free plan")
        self._plans = {p.id: p for p in plans}

    def get(self, plan_id: str) -> Plan:
        try:
            return self._plans[PlanId(plan_id)]
        except (ValueError, KeyError) as exc:
            raise UnknownPlanError(f"unknown plan '{plan_id}'") from exc

    def all(self) -> list[Plan]:
        return list(self._plans.values())

    @property
    def free(self) -> Plan:
        return self._plans[PlanId.FREE]


DEFAULT_CATALOG = PlanCatalog(
    [
        Plan(
            PlanId.FREE,
            "Free",
            0,
            "TRY",
            "forever",
            ("1 ekran", "SD kalite", "Reklamlı"),
            Entitlements(1, 1, "480p", False, True),
        ),
        Plan(
            PlanId.PERSONAL,
            "Personal",
            2999,
            "TRY",
            "monthly",
            ("2 ekran", "Full HD", "Reklamsız"),
            Entitlements(2, 2, "1080p", False, False, catchup_days=3),
        ),
        Plan(
            PlanId.DUO,
            "Duo",
            4499,
            "TRY",
            "monthly",
            ("3 ekran", "Full HD", "Reklamsız", "İndirme"),
            Entitlements(3, 3, "1080p", True, False, catchup_days=3),
        ),
        Plan(
            PlanId.FAMILY,
            "Family",
            6999,
            "TRY",
            "monthly",
            ("5 ekran", "4K", "Reklamsız", "İndirme", "Aile profilleri"),
            Entitlements(5, 5, "2160p", True, False, catchup_days=7),
        ),
    ]
)


class SubStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    GRACE = "grace"
    CANCELLED = "cancelled"  # cancelled but paid period still running
    EXPIRED = "expired"
    SUSPENDED = "suspended"


_ALLOWED: dict[SubStatus, frozenset[SubStatus]] = {
    SubStatus.TRIAL: frozenset({SubStatus.ACTIVE, SubStatus.EXPIRED, SubStatus.CANCELLED}),
    SubStatus.ACTIVE: frozenset(
        {SubStatus.ACTIVE, SubStatus.GRACE, SubStatus.CANCELLED, SubStatus.SUSPENDED, SubStatus.EXPIRED}
    ),
    SubStatus.GRACE: frozenset({SubStatus.ACTIVE, SubStatus.EXPIRED, SubStatus.SUSPENDED}),
    # CANCELLED → TRIAL: a cancelled trial that is resumed before it ends.
    SubStatus.CANCELLED: frozenset({SubStatus.ACTIVE, SubStatus.TRIAL, SubStatus.EXPIRED}),
    SubStatus.SUSPENDED: frozenset({SubStatus.ACTIVE, SubStatus.EXPIRED}),
    SubStatus.EXPIRED: frozenset({SubStatus.ACTIVE, SubStatus.TRIAL}),
}

GRANTS_ACCESS = frozenset({SubStatus.TRIAL, SubStatus.ACTIVE, SubStatus.GRACE, SubStatus.CANCELLED})


class IllegalTransitionError(Exception):
    def __init__(self, source: SubStatus, target: SubStatus) -> None:
        super().__init__(f"subscription transition {source} → {target} is not allowed")
        self.details = {"from": str(source), "to": str(target)}


def transition(current: str, target: SubStatus) -> SubStatus:
    source = SubStatus(current)
    if target not in _ALLOWED[source]:
        raise IllegalTransitionError(source, target)
    return target


class BillingError(Exception):
    pass


class TrialAlreadyUsedError(BillingError):
    pass


class NoPaidSubscriptionError(BillingError):
    pass


class PlanNotPurchasableError(BillingError):
    pass


class UnknownProviderError(BillingError):
    pass


class WebhookSignatureError(BillingError):
    pass


class WebhookReplayError(BillingError):
    pass


class AlreadySubscribedError(BillingError):
    pass


class NotResumableError(BillingError):
    pass


class CheckoutNotFoundError(BillingError):
    pass


# ── Pure lifecycle rules ───────────────────────────────────────────────────


def add_cycle(start: datetime, cycle: str) -> datetime:
    """Calendar-correct period arithmetic (Jan 31 + 1 month = Feb 28/29)."""
    if cycle == "monthly":
        months = 1
    elif cycle == "yearly":
        months = 12
    else:
        raise ValueError(f"cycle '{cycle}' has no period")
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


@dataclass(frozen=True, slots=True)
class SubscriptionState:
    """The fields of a subscription the lifecycle rules depend on (ORM-free)."""

    plan: str
    status: str
    current_period_end: datetime | None
    trial_ends_at: datetime | None
    grace_ends_at: datetime | None


def access_until(state: SubscriptionState) -> datetime | None:
    """When the paid access granted by ``state`` ends (``None`` = free tier / no end)."""
    status = SubStatus(state.status)
    if state.plan == PlanId.FREE:
        return None
    if status is SubStatus.TRIAL:
        return state.trial_ends_at
    if status is SubStatus.GRACE:
        return state.grace_ends_at
    if status is SubStatus.CANCELLED:
        return state.current_period_end or state.trial_ends_at
    return state.current_period_end


def effective_plan(state: SubscriptionState, catalog: PlanCatalog, now: datetime, grace: timedelta) -> Plan:
    """The plan whose entitlements apply *right now*.

    Defensive against a lagging expiry job: a paid status whose access window
    has already closed yields the free plan even before the row is rewritten.
    An ACTIVE paid subscription whose renewal is late keeps access for the
    configured grace window (the PSP may still be retrying the charge).
    """
    if state.plan == PlanId.FREE or SubStatus(state.status) not in GRANTS_ACCESS:
        return catalog.free
    until = access_until(state)
    if until is not None:
        if SubStatus(state.status) is SubStatus.ACTIVE:
            until = until + grace
        if until <= now:
            return catalog.free
    try:
        return catalog.get(state.plan)
    except UnknownPlanError:
        return catalog.free  # a retired plan id must never crash playback


def lifecycle_status(state: SubscriptionState) -> SubStatus:
    """The free tier is modelled as ``plan=free,status=active`` but is, for the
    paid lifecycle, equivalent to "no paid subscription" (EXPIRED)."""
    return SubStatus.EXPIRED if state.plan == PlanId.FREE else SubStatus(state.status)
