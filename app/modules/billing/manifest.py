from __future__ import annotations

from typing import Any

from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.billing.api import BillingReports, EntitlementsReader
from app.modules.billing.domain import (
    DEFAULT_CATALOG,
    AlreadySubscribedError,
    CheckoutNotFoundError,
    IllegalTransitionError,
    NoPaidSubscriptionError,
    NotResumableError,
    PlanCatalog,
    PlanNotPurchasableError,
    TrialAlreadyUsedError,
    UnknownPlanError,
    UnknownProviderError,
    WebhookReplayError,
    WebhookSignatureError,
)
from app.modules.billing.providers import PaymentProviderRegistry
from app.shared_kernel.events import UserRegistered


def _services(c: Any) -> None:
    from app.modules.billing.services import (
        BillingReportService,
        BillingService,
        EntitlementService,
        build_provider_registry,
    )

    c.register(PlanCatalog, lambda c: DEFAULT_CATALOG)
    c.register(PaymentProviderRegistry, lambda c: build_provider_registry(c.resolve(Settings)))
    c.register(
        BillingService,
        lambda c: BillingService(
            uow=c.resolve(UnitOfWorkFactory),
            catalog=c.resolve(PlanCatalog),
            providers=c.resolve(PaymentProviderRegistry),
            clock=c.resolve(Clock),
            trial_days=c.resolve(Settings).trial_days,
            grace_days=c.resolve(Settings).grace_days,
            return_url=f"{c.resolve(Settings).frontend_base_url.rstrip('/')}/billing/return",
        ),
    )
    c.register(
        EntitlementsReader,
        lambda c: EntitlementService(
            c.resolve(UnitOfWorkFactory), c.resolve(PlanCatalog), c.resolve(Clock), c.resolve(Settings).grace_days
        ),
    )
    c.register(
        BillingReports,
        lambda c: BillingReportService(
            c.resolve(UnitOfWorkFactory), c.resolve(PlanCatalog), c.resolve(Clock), c.resolve(Settings).grace_days
        ),
    )


manifest = ModuleManifest(
    name="billing",
    version="2.0.0",
    description="Plan catalogue (single source of entitlements), subscription lifecycle, PSP webhooks.",
    provides={"billing.entitlements": EntitlementsReader, "billing.reports": BillingReports},
    requires=frozenset({"identity.authentication"}),
    models=("app.modules.billing.models",),
    services=_services,
    routes=(RouteSpec("app.modules.billing.http:blueprint", "/api/v1/billing"),),
    subscriptions=(
        SubscriptionSpec(
            UserRegistered.NAME, "billing.create_free_subscription", "app.modules.billing.handlers:on_user_registered"
        ),
    ),
    task_modules=("app.modules.billing.tasks",),
    beat_schedule={"billing.expire-due": {"task": "billing.expire_due_subscriptions", "schedule": 300.0}},
    error_map={
        UnknownPlanError: (404, "PLAN_NOT_FOUND"),
        PlanNotPurchasableError: (422, "PLAN_NOT_PURCHASABLE"),
        AlreadySubscribedError: (409, "ALREADY_SUBSCRIBED"),
        TrialAlreadyUsedError: (409, "TRIAL_ALREADY_USED"),
        NoPaidSubscriptionError: (409, "NO_PAID_SUBSCRIPTION"),
        NotResumableError: (409, "NOT_RESUMABLE"),
        CheckoutNotFoundError: (404, "CHECKOUT_NOT_FOUND"),
        IllegalTransitionError: (409, "SUBSCRIPTION_TRANSITION_INVALID"),
        UnknownProviderError: (404, "PAYMENT_PROVIDER_UNKNOWN"),
        WebhookSignatureError: (400, "WEBHOOK_SIGNATURE_INVALID"),
        WebhookReplayError: (400, "WEBHOOK_REPLAYED"),
    },
)
