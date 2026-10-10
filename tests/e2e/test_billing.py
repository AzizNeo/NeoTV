"""Billing lifecycle end to end (fake PSP → real webhook path)."""

from __future__ import annotations

import json
import time
from datetime import timedelta

from flask import Flask

from app.kernel.container import resolve
from app.kernel.db import db
from app.kernel.time import utcnow
from app.modules.billing.models import Subscription
from app.modules.billing.providers import SIGNATURE_HEADER, sign_payload
from app.modules.billing.services import BillingService
from tests.support.client import Api


def _subscription(app: Flask, user_id: int) -> Subscription:
    with app.app_context():
        sub = db.session.query(Subscription).filter_by(user_id=user_id).one()
        db.session.expunge(sub)
        return sub


def test_new_account_is_on_the_free_tier(api: Api, viewer: str) -> None:
    sub = api.get("/api/v1/billing/subscription", token=viewer).data
    assert (sub["plan"], sub["effective_plan"], sub["trial_available"]) == ("free", "free", True)
    assert sub["entitlements"]["max_streams"] == 1
    plans = api.get("/api/v1/billing/plans").data
    assert [p["id"] for p in plans] == ["free", "personal", "duo", "family"]


def test_trial_once_cancel_resume(api: Api, viewer: str) -> None:
    trial = api.post("/api/v1/billing/trial", token=viewer)
    assert trial.data["status"] == "trial" and trial.data["effective_plan"] == "family"
    assert api.post("/api/v1/billing/trial", token=viewer).code == "TRIAL_ALREADY_USED"
    cancelled = api.post("/api/v1/billing/subscription/cancel", token=viewer).data
    assert cancelled["status"] == "cancelled" and cancelled["effective_plan"] == "family"
    resumed = api.post("/api/v1/billing/subscription/resume", token=viewer).data
    assert resumed["status"] == "trial"


def test_checkout_is_idempotent_and_completes_via_signed_webhook(api: Api, viewer: str) -> None:
    headers = {"Idempotency-Key": "chk-1"}
    first = api.post("/api/v1/billing/checkout", token=viewer, json={"plan": "duo"}, headers=headers)
    again = api.post("/api/v1/billing/checkout", token=viewer, json={"plan": "duo"}, headers=headers)
    assert first.status == 201 and again.data["checkout_id"] == first.data["checkout_id"]
    assert api.post("/api/v1/billing/checkout", token=viewer, json={"plan": "free"}).status == 422

    done = api.post(f"/api/v1/billing/dev/checkouts/{first.data['checkout_id']}/complete", token=viewer)
    assert done.data["outcome"] == "applied"
    sub = api.get("/api/v1/billing/subscription", token=viewer).data
    assert (sub["plan"], sub["status"], sub["entitlements"]["max_streams"]) == ("duo", "active", 3)
    repeat = api.post(f"/api/v1/billing/dev/checkouts/{first.data['checkout_id']}/complete", token=viewer)
    assert repeat.data["outcome"] == "ignored"  # checkout already completed


def test_webhook_security_and_duplicate_delivery(api: Api, app: Flask, viewer: str) -> None:
    with app.app_context():
        from app.kernel.settings import Settings

        key = resolve(Settings).derive_key("billing.webhook")
    body = json.dumps(
        {"id": "evt_dup", "type": "payment.failed", "created": int(time.time()), "data": {"user_id": 2}}
    ).encode()
    signed = {SIGNATURE_HEADER: sign_payload(key, body), "Content-Type": "application/json"}
    assert api.post("/api/v1/billing/webhooks/fake", data=body, headers=signed).data["outcome"] == "ignored"
    assert api.post("/api/v1/billing/webhooks/fake", data=body, headers=signed).data["outcome"] == "duplicate"
    tampered = {**signed, SIGNATURE_HEADER: sign_payload(b"attacker", body)}
    assert api.post("/api/v1/billing/webhooks/fake", data=body, headers=tampered).code == "WEBHOOK_SIGNATURE_INVALID"
    assert api.post("/api/v1/billing/webhooks/stripe", data=body, headers=signed).code == "PAYMENT_PROVIDER_UNKNOWN"


def _uid(api: Api, token: str) -> int:
    return int(api.get("/api/v1/auth/me", token=token).data["id"])


def test_expiry_job_downgrades_and_emits(api: Api, app: Flask, viewer: str) -> None:
    api.post("/api/v1/billing/trial", token=viewer)
    with app.app_context():
        sub = db.session.query(Subscription).filter_by(user_id=_uid(api, viewer)).one()
        sub.trial_ends_at = utcnow() - timedelta(minutes=1)
        db.session.commit()
        assert resolve(BillingService).expire_due() == 1
    sub = api.get("/api/v1/billing/subscription", token=viewer).data
    assert (sub["plan"], sub["status"], sub["trial_available"]) == ("free", "active", False)


def test_downgrade_trims_running_streams(api: Api, app: Flask, admin: str, viewer: str) -> None:
    api.post("/api/v1/billing/trial", token=viewer)  # 5 streams
    refs = [api.channel(admin, f"Ch {i}")["ref"] for i in range(3)]
    for i, ref in enumerate(refs):
        assert api.open_session(viewer, ref, headers={"X-Device-ID": f"device-{i}"}).status == 201
    with app.app_context():
        from app.modules.playback.concurrency import StreamConcurrencyGuard

        assert resolve(StreamConcurrencyGuard).active_count(2) == 3
        sub = db.session.query(Subscription).filter_by(user_id=2).one()
        sub.trial_ends_at = utcnow() - timedelta(minutes=1)
        db.session.commit()
        # Run as the beat job does (a Celery task): its post-run hook dispatches the
        # outbox, so playback's SubscriptionChanged consumer trims the extra streams.
        from app.modules.billing.tasks import expire_due_subscriptions

        expire_due_subscriptions.apply()
        assert resolve(StreamConcurrencyGuard).active_count(2) == 1
