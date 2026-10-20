"""Billing HTTP adapter: /api/v1/billing."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from flask import Blueprint, g, request
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.errors import ApiError
from app.kernel.resilience.rate_limit import Rate
from app.kernel.security.auth import current_user
from app.kernel.settings import Settings
from app.modules.billing.services import BillingService

blueprint = Blueprint("billing", __name__)

_TAGS = ("billing",)


class EntitlementsOut(BaseModel):
    max_streams: int
    max_profiles: int
    max_resolution: str
    offline_downloads: bool
    ads: bool
    catchup_days: int = Field(description="Days of archived live TV the plan can watch (0 = none)")


class PlanOut(BaseModel):
    id: str
    display_name: str
    price_minor: int
    currency: str
    cycle: str
    features: list[str]
    entitlements: EntitlementsOut


class SubscriptionOut(BaseModel):
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
    entitlements: EntitlementsOut


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: Literal["personal", "duo", "family"]


class CheckoutOut(BaseModel):
    checkout_id: str
    provider: str
    plan: str
    redirect_url: str
    status: str


class WebhookOut(BaseModel):
    event_id: str
    type: str
    outcome: str


@blueprint.get("/plans")
@endpoint(
    auth="public",
    summary="Plan catalogue",
    tags=_TAGS,
    response=list[PlanOut],
    rate=Rate("billing.plans", rps=5, burst=20, per="ip"),
)
def plans() -> object:
    return resolve(BillingService).plans()


@blueprint.get("/subscription")
@endpoint(summary="Current subscription and effective entitlements", tags=_TAGS, response=SubscriptionOut)
def subscription() -> object:
    return resolve(BillingService).subscription(current_user.id)


@blueprint.post("/checkout")
@endpoint(
    summary="Start a hosted checkout for a paid plan",
    tags=_TAGS,
    body=CheckoutRequest,
    response=CheckoutOut,
    status=201,
    idempotency="billing.checkout",
    rate=Rate("billing.checkout", rps=0.5, burst=5),
    errors=("PLAN_NOT_PURCHASABLE", "ALREADY_SUBSCRIBED"),
)
def checkout(body: CheckoutRequest) -> object:
    return resolve(BillingService).request_checkout(
        user_id=current_user.id, plan_id=body.plan, idempotency_key=g.get("idempotency_key")
    )


@blueprint.post("/trial")
@endpoint(
    summary="Start the one-time free trial",
    tags=_TAGS,
    response=SubscriptionOut,
    idempotency="billing.trial",
    errors=("TRIAL_ALREADY_USED", "ALREADY_SUBSCRIBED"),
)
def trial() -> object:
    return resolve(BillingService).start_trial(user_id=current_user.id)


@blueprint.post("/subscription/cancel")
@endpoint(summary="Cancel at period end", tags=_TAGS, response=SubscriptionOut, errors=("NO_PAID_SUBSCRIPTION",))
def cancel() -> object:
    return resolve(BillingService).cancel(user_id=current_user.id)


@blueprint.post("/subscription/resume")
@endpoint(summary="Undo a pending cancellation", tags=_TAGS, response=SubscriptionOut, errors=("NOT_RESUMABLE",))
def resume() -> object:
    return resolve(BillingService).resume(user_id=current_user.id)


@blueprint.post("/webhooks/<provider>")
@endpoint(
    auth="public",
    summary="Payment provider webhook (signature-verified, idempotent)",
    tags=_TAGS,
    response=WebhookOut,
    rate=Rate("billing.webhook", rps=20, burst=100, per="ip"),
    errors=("WEBHOOK_SIGNATURE_INVALID", "WEBHOOK_REPLAYED", "PAYMENT_PROVIDER_UNKNOWN"),
)
def webhook(provider: str) -> object:
    # The signature covers the exact bytes: never re-serialise the JSON.
    return resolve(BillingService).apply_provider_event(
        provider_name=provider, raw_body=request.get_data(cache=False), headers=request.headers
    )


@blueprint.post("/dev/checkouts/<checkout_id>/complete")
@endpoint(summary="[dev/test only] Complete a fake-provider checkout", tags=_TAGS, response=WebhookOut)
def dev_complete_checkout(checkout_id: str) -> object:
    if resolve(Settings).env not in {"dev", "test"}:
        raise ApiError("NOT_FOUND", 404)
    return resolve(BillingService).simulate_checkout_completion(user_id=current_user.id, checkout_id=checkout_id)
