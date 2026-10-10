"""Billing application services.

* ``BillingService`` — the only writer of subscriptions. Every state change
  goes through :func:`app.modules.billing.domain.transition` (illegal moves are
  named errors, never silent overwrites) and emits ``SubscriptionChanged`` via
  the transactional outbox in the *same* transaction.
* Webhooks are idempotent at the storage level: ``billing_webhook_events`` has
  PK ``(provider, event_id)`` and the insert is ``ON CONFLICT DO NOTHING``; a
  PSP retry is acknowledged without touching the subscription twice.
* ``EntitlementService`` — the read side published as capability
  ``billing.entitlements``. It never writes, never raises for a missing row
  and is defensive against a lagging expiry job (see ``effective_plan``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.kernel.db import dialect_insert
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWork, UnitOfWorkFactory
from app.modules.billing.domain import (
    AlreadySubscribedError,
    CheckoutNotFoundError,
    Entitlements,
    NoPaidSubscriptionError,
    NotResumableError,
    Plan,
    PlanCatalog,
    PlanId,
    PlanNotPurchasableError,
    SubscriptionState,
    SubStatus,
    TrialAlreadyUsedError,
    add_cycle,
    effective_plan,
    lifecycle_status,
    transition,
)
from app.modules.billing.models import CheckoutSession, Subscription, WebhookEventRecord
from app.modules.billing.providers import FakePaymentProvider, HeaderLookup, PaymentProviderRegistry, ProviderEvent
from app.shared_kernel.events import SubscriptionChanged

TRIAL_PLAN = PlanId.FAMILY
EXPIRY_BATCH = 200


# ── Read models ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PlanView:
    id: str
    display_name: str
    price_minor: int
    currency: str
    cycle: str
    features: list[str]
    entitlements: Entitlements

    @classmethod
    def of(cls, plan: Plan) -> PlanView:
        return cls(
            id=str(plan.id),
            display_name=plan.display_name,
            price_minor=plan.price_minor,
            currency=plan.currency,
            cycle=plan.cycle,
            features=list(plan.features),
            entitlements=plan.entitlements,
        )


@dataclass(frozen=True, slots=True)
class SubscriptionView:
    plan: str
    effective_plan: str
    status: str
    cycle: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    trial_ends_at: datetime | None
    grace_ends_at: datetime | None
    cancel_at_period_end: bool
    trial_available: bool
    entitlements: Entitlements


@dataclass(frozen=True, slots=True)
class CheckoutView:
    checkout_id: str
    provider: str
    plan: str
    redirect_url: str
    status: str


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    event_id: str
    type: str
    outcome: str  # applied | duplicate | ignored


def _state(sub: Subscription) -> SubscriptionState:
    return SubscriptionState(
        plan=sub.plan,
        status=sub.status,
        current_period_end=sub.current_period_end,
        trial_ends_at=sub.trial_ends_at,
        grace_ends_at=sub.grace_ends_at,
    )


# ── Persistence ────────────────────────────────────────────────────────────


class SubscriptionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find(self, user_id: int) -> Subscription | None:
        return self._session.execute(select(Subscription).where(Subscription.user_id == user_id)).scalar_one_or_none()

    def ensure(self, user_id: int, now: datetime) -> Subscription:
        """Race-free get-or-create (unique ``user_id`` + ON CONFLICT DO NOTHING),
        then a locking read so concurrent writers serialise on the row."""
        stmt = dialect_insert(self._session, Subscription.__table__).values(
            user_id=user_id,
            plan=str(PlanId.FREE),
            status=str(SubStatus.ACTIVE),
            cycle="forever",
            trial_used=False,
            cancel_at_period_end=False,
            created_at=now,
            updated_at=now,
        )
        self._session.execute(stmt.on_conflict_do_nothing(index_elements=["user_id"]))
        return self._session.execute(
            select(Subscription).where(Subscription.user_id == user_id).with_for_update()
        ).scalar_one()

    def due_for_expiry(self, now: datetime, active_grace: timedelta, limit: int) -> list[Subscription]:
        paid = Subscription.plan != str(PlanId.FREE)
        due = or_(
            and_(Subscription.status == str(SubStatus.TRIAL), Subscription.trial_ends_at <= now),
            and_(Subscription.status == str(SubStatus.GRACE), Subscription.grace_ends_at <= now),
            and_(
                Subscription.status == str(SubStatus.CANCELLED),
                or_(
                    Subscription.current_period_end <= now,
                    and_(Subscription.current_period_end.is_(None), Subscription.trial_ends_at <= now),
                ),
            ),
            and_(Subscription.status == str(SubStatus.ACTIVE), Subscription.current_period_end <= now - active_grace),
        )
        return list(
            self._session.execute(
                select(Subscription)
                .where(paid, due)
                .order_by(Subscription.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).scalars()
        )


# ── Write side ─────────────────────────────────────────────────────────────


class BillingService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        catalog: PlanCatalog,
        providers: PaymentProviderRegistry,
        clock: Clock,
        trial_days: int,
        grace_days: int,
        return_url: str,
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._providers = providers
        self._clock = clock
        self._trial = timedelta(days=trial_days)
        self._grace = timedelta(days=grace_days)
        self._return_url = return_url
        self._handlers: Mapping[str, Callable[[UnitOfWork, Subscription, ProviderEvent, datetime], bool]] = {
            "checkout.completed": self._on_checkout_completed,
            "payment.succeeded": self._on_payment_succeeded,
            "payment.failed": self._on_payment_failed,
            "subscription.cancelled": self._on_subscription_cancelled,
            "subscription.expired": self._on_subscription_expired,
        }

    # queries ---------------------------------------------------------------
    def plans(self) -> list[PlanView]:
        return [PlanView.of(p) for p in self._catalog.all()]

    def subscription(self, user_id: int) -> SubscriptionView:
        with self._uow() as uow:
            return self._view(SubscriptionRepository(uow.session).ensure(user_id, self._clock.now()))

    # lifecycle -------------------------------------------------------------
    def ensure_free(self, session: Session, user_id: int) -> None:
        """Used by the ``UserRegistered`` consumer (inside its UoW)."""
        SubscriptionRepository(session).ensure(user_id, self._clock.now())

    def request_checkout(self, *, user_id: int, plan_id: str, idempotency_key: str | None) -> CheckoutView:
        plan = self._catalog.get(plan_id)
        if not plan.is_paid:
            raise PlanNotPurchasableError(f"plan '{plan.id}' cannot be purchased")
        key = idempotency_key or uuid.uuid4().hex
        provider = self._providers.default
        with self._uow() as uow:
            existing = uow.session.execute(
                select(CheckoutSession).where(
                    CheckoutSession.user_id == user_id, CheckoutSession.idempotency_key == key
                )
            ).scalar_one_or_none()
            if existing is not None:
                return self._checkout_view(existing)
            sub = SubscriptionRepository(uow.session).ensure(user_id, self._clock.now())
            if lifecycle_status(_state(sub)) in {SubStatus.ACTIVE, SubStatus.GRACE} and sub.plan == str(plan.id):
                raise AlreadySubscribedError(f"already subscribed to '{plan.id}'")
            started = provider.create_checkout(
                user_id=user_id, plan=str(plan.id), idempotency_key=key, return_url=self._return_url
            )
            checkout = CheckoutSession(
                id=started.session_id,
                provider=provider.name,
                user_id=user_id,
                plan=str(plan.id),
                status="pending",
                redirect_url=started.redirect_url,
                idempotency_key=key,
                created_at=self._clock.now(),
            )
            uow.session.add(checkout)
            uow.flush()
            return self._checkout_view(checkout)

    def start_trial(self, *, user_id: int) -> SubscriptionView:
        now = self._clock.now()
        with self._uow() as uow:
            sub = SubscriptionRepository(uow.session).ensure(user_id, now)
            if sub.trial_used:
                raise TrialAlreadyUsedError("the free trial has already been used on this account")
            source = lifecycle_status(_state(sub))
            if source is not SubStatus.EXPIRED:
                raise AlreadySubscribedError("a paid subscription is already running")
            transition(source, SubStatus.TRIAL)
            sub.plan = str(TRIAL_PLAN)
            sub.status = str(SubStatus.TRIAL)
            sub.cycle = self._catalog.get(TRIAL_PLAN).cycle
            sub.trial_used = True
            sub.trial_ends_at = now + self._trial
            sub.current_period_start = now
            sub.current_period_end = None
            sub.grace_ends_at = None
            sub.cancel_at_period_end = False
            sub.cancelled_at = None
            self._emit(uow, sub, now)
            return self._view(sub)

    def cancel(self, *, user_id: int) -> SubscriptionView:
        now = self._clock.now()
        with self._uow() as uow:
            sub = SubscriptionRepository(uow.session).ensure(user_id, now)
            if lifecycle_status(_state(sub)) not in {SubStatus.ACTIVE, SubStatus.TRIAL, SubStatus.GRACE}:
                raise NoPaidSubscriptionError("there is no running paid subscription to cancel")
            if SubStatus(sub.status) is SubStatus.GRACE:
                # Payment already failing: cancelling ends access now.
                self._downgrade_to_free(sub, now)
            else:
                sub.status = str(transition(sub.status, SubStatus.CANCELLED))
                sub.cancel_at_period_end = True
                sub.cancelled_at = now
            self._emit(uow, sub, now)
            return self._view(sub)

    def resume(self, *, user_id: int) -> SubscriptionView:
        now = self._clock.now()
        with self._uow() as uow:
            sub = SubscriptionRepository(uow.session).ensure(user_id, now)
            if sub.plan == str(PlanId.FREE) or SubStatus(sub.status) is not SubStatus.CANCELLED:
                raise NotResumableError("only a cancelled subscription can be resumed")
            was_trial = sub.current_period_end is None and sub.trial_ends_at is not None
            ends = sub.trial_ends_at if was_trial else sub.current_period_end
            if ends is None or ends <= now:
                raise NotResumableError("the paid period has already ended; start a new checkout")
            sub.status = str(transition(sub.status, SubStatus.TRIAL if was_trial else SubStatus.ACTIVE))
            sub.cancel_at_period_end = False
            sub.cancelled_at = None
            self._emit(uow, sub, now)
            return self._view(sub)

    # webhooks ------------------------------------------------------------
    def apply_provider_event(self, *, provider_name: str, raw_body: bytes, headers: HeaderLookup) -> WebhookOutcome:
        provider = self._providers.get(provider_name)
        event = provider.verify_webhook(raw_body=raw_body, headers=headers)  # raises before any write
        now = self._clock.now()
        with self._uow() as uow:
            inserted = (
                uow.session.execute(
                    dialect_insert(uow.session, WebhookEventRecord.__table__)
                    .values(
                        provider=provider.name,
                        event_id=event.event_id,
                        event_type=event.type,
                        outcome="applied",
                        received_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["provider", "event_id"])
                    .returning(WebhookEventRecord.__table__.c.event_id)
                ).first()
                is not None
            )
            if not inserted:
                return WebhookOutcome(event.event_id, event.type, "duplicate")
            handler = self._handlers.get(event.type)
            if handler is None:
                self._record_outcome(uow.session, provider.name, event.event_id, "ignored")
                return WebhookOutcome(event.event_id, event.type, "ignored")
            sub = SubscriptionRepository(uow.session).ensure(event.user_id, now)
            changed = handler(uow, sub, event, now)
            if changed:
                sub.provider = provider.name
                if event.external_subscription_id:
                    sub.external_subscription_id = event.external_subscription_id
                self._emit(uow, sub, now)
            else:
                self._record_outcome(uow.session, provider.name, event.event_id, "ignored")
            return WebhookOutcome(event.event_id, event.type, "applied" if changed else "ignored")

    def simulate_checkout_completion(self, *, user_id: int, checkout_id: str) -> WebhookOutcome:
        """Development only: the fake PSP's "pay" button. Produces a correctly
        signed webhook and feeds it through the production webhook path."""
        provider = self._providers.get(FakePaymentProvider.name)
        if not isinstance(provider, FakePaymentProvider):  # pragma: no cover - registry invariant
            raise CheckoutNotFoundError("fake provider is not configured")
        with self._uow() as uow:
            checkout = uow.session.get(CheckoutSession, checkout_id)
            if checkout is None or checkout.user_id != user_id or checkout.provider != provider.name:
                raise CheckoutNotFoundError("checkout not found")
            plan = checkout.plan
        body, headers = provider.signed_event(
            event_type="checkout.completed", user_id=user_id, plan=plan, checkout_id=checkout_id
        )
        return self.apply_provider_event(provider_name=provider.name, raw_body=body, headers=headers)

    # scheduled -----------------------------------------------------------
    def expire_due(self) -> int:
        """Beat job: closes elapsed trials/periods/grace windows. Batched and
        ``SKIP LOCKED`` so overlapping runs never process the same row."""
        total = 0
        while True:
            now = self._clock.now()
            with self._uow() as uow:
                batch = SubscriptionRepository(uow.session).due_for_expiry(now, self._grace, EXPIRY_BATCH)
                for sub in batch:
                    if SubStatus(sub.status) is SubStatus.ACTIVE:
                        # Renewal is late beyond grace without a payment.failed webhook.
                        sub.status = str(transition(sub.status, SubStatus.GRACE))
                    self._downgrade_to_free(sub, now)
                    self._emit(uow, sub, now)
            total += len(batch)
            if len(batch) < EXPIRY_BATCH:
                return total

    # event handlers (inside the webhook UoW) -------------------------------
    def _on_checkout_completed(self, uow: UnitOfWork, sub: Subscription, event: ProviderEvent, now: datetime) -> bool:
        if not event.checkout_id:
            raise CheckoutNotFoundError("checkout.completed without checkout_id")
        checkout = uow.session.get(CheckoutSession, event.checkout_id, with_for_update=True)
        if checkout is None or checkout.user_id != event.user_id:
            raise CheckoutNotFoundError("checkout not found for this user")
        if checkout.status == "completed":
            return False
        checkout.status = "completed"
        checkout.completed_at = now
        plan = self._catalog.get(checkout.plan)
        sub.status = str(transition(lifecycle_status(_state(sub)), SubStatus.ACTIVE))
        sub.plan = str(plan.id)
        sub.cycle = plan.cycle
        sub.current_period_start = now
        sub.current_period_end = add_cycle(now, plan.cycle)
        sub.trial_ends_at = None
        sub.grace_ends_at = None
        sub.cancel_at_period_end = False
        sub.cancelled_at = None
        return True

    def _on_payment_succeeded(self, uow: UnitOfWork, sub: Subscription, event: ProviderEvent, now: datetime) -> bool:
        if sub.plan == str(PlanId.FREE) and not event.plan:
            return False  # renewal for a subscription we no longer track
        plan = self._catalog.get(event.plan or sub.plan)
        anchor = sub.current_period_end if sub.current_period_end and sub.current_period_end > now else now
        sub.status = str(transition(lifecycle_status(_state(sub)), SubStatus.ACTIVE))
        sub.plan = str(plan.id)
        sub.cycle = plan.cycle
        sub.current_period_start = anchor
        sub.current_period_end = add_cycle(anchor, plan.cycle)
        sub.grace_ends_at = None
        sub.trial_ends_at = None
        return True

    def _on_payment_failed(self, uow: UnitOfWork, sub: Subscription, event: ProviderEvent, now: datetime) -> bool:
        if SubStatus(sub.status) is not SubStatus.ACTIVE or sub.plan == str(PlanId.FREE):
            return False
        sub.status = str(transition(sub.status, SubStatus.GRACE))
        sub.grace_ends_at = now + self._grace
        return True

    def _on_subscription_cancelled(
        self, uow: UnitOfWork, sub: Subscription, event: ProviderEvent, now: datetime
    ) -> bool:
        if sub.plan == str(PlanId.FREE) or SubStatus(sub.status) in {SubStatus.CANCELLED, SubStatus.EXPIRED}:
            return False
        if SubStatus(sub.status) is SubStatus.GRACE:
            self._downgrade_to_free(sub, now)
            return True
        sub.status = str(transition(sub.status, SubStatus.CANCELLED))
        sub.cancel_at_period_end = True
        sub.cancelled_at = now
        return True

    def _on_subscription_expired(self, uow: UnitOfWork, sub: Subscription, event: ProviderEvent, now: datetime) -> bool:
        if sub.plan == str(PlanId.FREE):
            return False
        self._downgrade_to_free(sub, now)
        return True

    # helpers -------------------------------------------------------------
    def _downgrade_to_free(self, sub: Subscription, now: datetime) -> None:
        """Validated move to EXPIRED, then normalised to the single free-tier
        representation (``plan=free,status=active``) every new user also has."""
        transition(sub.status, SubStatus.EXPIRED)
        sub.plan = str(PlanId.FREE)
        sub.status = str(SubStatus.ACTIVE)
        sub.cycle = self._catalog.free.cycle
        sub.current_period_start = now
        sub.current_period_end = None
        sub.trial_ends_at = None
        sub.grace_ends_at = None
        sub.cancel_at_period_end = False

    def _emit(self, uow: UnitOfWork, sub: Subscription, now: datetime) -> None:
        plan = effective_plan(_state(sub), self._catalog, now, self._grace)
        uow.outbox.add(
            SubscriptionChanged(
                user_id=sub.user_id,
                plan=sub.plan,
                status=sub.status,
                max_streams=plan.entitlements.max_streams,
                effective_at=now.isoformat(),
            )
        )

    @staticmethod
    def _record_outcome(session: Session, provider: str, event_id: str, outcome: str) -> None:
        record = session.get(WebhookEventRecord, (provider, event_id))
        if record is not None:
            record.outcome = outcome

    def _view(self, sub: Subscription) -> SubscriptionView:
        now = self._clock.now()
        plan = effective_plan(_state(sub), self._catalog, now, self._grace)
        return SubscriptionView(
            plan=sub.plan,
            effective_plan=str(plan.id),
            status=sub.status,
            cycle=sub.cycle,
            current_period_start=sub.current_period_start,
            current_period_end=sub.current_period_end,
            trial_ends_at=sub.trial_ends_at,
            grace_ends_at=sub.grace_ends_at,
            cancel_at_period_end=bool(sub.cancel_at_period_end),
            trial_available=not sub.trial_used and lifecycle_status(_state(sub)) is SubStatus.EXPIRED,
            entitlements=plan.entitlements,
        )

    @staticmethod
    def _checkout_view(checkout: CheckoutSession) -> CheckoutView:
        return CheckoutView(
            checkout_id=checkout.id,
            provider=checkout.provider,
            plan=checkout.plan,
            redirect_url=checkout.redirect_url,
            status=checkout.status,
        )


# ── Read side (capability billing.entitlements) ───────────────────────────


class EntitlementService:
    def __init__(self, uow: UnitOfWorkFactory, catalog: PlanCatalog, clock: Clock, grace_days: int) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock
        self._grace = timedelta(days=grace_days)

    def for_user(self, user_id: int) -> Entitlements:
        with self._uow() as uow:
            sub = SubscriptionRepository(uow.session).find(user_id)
            if sub is None:
                return self._catalog.free.entitlements
            return effective_plan(_state(sub), self._catalog, self._clock.now(), self._grace).entitlements


class BillingReportService:
    """Capability ``billing.reports``."""

    def __init__(self, uow: UnitOfWorkFactory, catalog: PlanCatalog, clock: Clock, grace_days: int) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock
        self._grace = timedelta(days=grace_days)

    def plan_distribution(self) -> dict[str, int]:
        """Effective plan → number of accounts (accounts without a row count as free)."""
        now = self._clock.now()
        result: dict[str, int] = {}
        with self._uow() as uow:
            for sub in uow.session.execute(select(Subscription).where(Subscription.plan != str(PlanId.FREE))).scalars():
                plan = str(effective_plan(_state(sub), self._catalog, now, self._grace).id)
                result[plan] = result.get(plan, 0) + 1
            free_rows = uow.session.execute(
                select(func.count(Subscription.id)).where(Subscription.plan == str(PlanId.FREE))
            ).scalar_one()
        result[str(PlanId.FREE)] = result.get(str(PlanId.FREE), 0) + int(free_rows)
        return result

    def effective_plans(self, user_ids: list[int]) -> dict[int, str]:
        if not user_ids:
            return {}
        now = self._clock.now()
        with self._uow() as uow:
            rows = uow.session.execute(select(Subscription).where(Subscription.user_id.in_(user_ids))).scalars()
            found = {s.user_id: str(effective_plan(_state(s), self._catalog, now, self._grace).id) for s in rows}
        return {uid: found.get(uid, str(PlanId.FREE)) for uid in user_ids}


def build_provider_registry(settings: Any) -> PaymentProviderRegistry:
    """Adapter wiring. A new PSP = one adapter + one line here (+ contract tests)."""
    from app.modules.billing.providers import HmacPaymentProvider

    secret = (
        settings.payment_webhook_secret.get_secret_value().encode()
        if settings.payment_webhook_secret is not None
        else settings.derive_key("billing.webhook")
    )
    providers: list[Any] = []
    if settings.payment_provider == "hmac":
        providers.append(
            HmacPaymentProvider(secret=secret, checkout_url_template=settings.payment_checkout_url_template)
        )
    if settings.env in {"dev", "test"} or settings.payment_provider == "fake":
        providers.append(FakePaymentProvider(secret=secret, frontend_base_url=settings.frontend_base_url))
    return PaymentProviderRegistry(providers, default=settings.payment_provider)
