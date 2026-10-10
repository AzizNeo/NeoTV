from __future__ import annotations

from app.kernel.db import UTCDateTime, created_at_column, db, updated_at_column


class Subscription(db.Model):
    __tablename__ = "billing_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, unique=True)  # soft reference to identity
    plan = db.Column(db.String(30), nullable=False, default="free")
    status = db.Column(db.String(20), nullable=False, default="active")
    cycle = db.Column(db.String(20), nullable=False, default="forever")
    current_period_start = db.Column(UTCDateTime())
    current_period_end = db.Column(UTCDateTime())
    trial_ends_at = db.Column(UTCDateTime())
    trial_used = db.Column(db.Boolean, nullable=False, default=False)
    grace_ends_at = db.Column(UTCDateTime())
    cancel_at_period_end = db.Column(db.Boolean, nullable=False, default=False)
    cancelled_at = db.Column(UTCDateTime())
    provider = db.Column(db.String(30))
    external_subscription_id = db.Column(db.String(128))
    created_at = created_at_column()
    updated_at = updated_at_column()

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('trial','active','grace','cancelled','expired','suspended')", name="status_valid"
        ),
        db.Index("ix_billing_subscriptions_status_period", "status", "current_period_end"),
    )


class CheckoutSession(db.Model):
    __tablename__ = "billing_checkouts"

    id = db.Column(db.String(64), primary_key=True)  # provider session id
    provider = db.Column(db.String(30), nullable=False)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    plan = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    redirect_url = db.Column(db.String(1000), nullable=False)
    idempotency_key = db.Column(db.String(128), nullable=False)
    created_at = created_at_column()
    completed_at = db.Column(UTCDateTime())

    __table_args__ = (
        db.UniqueConstraint("user_id", "idempotency_key", name="uq_billing_checkouts_user_id_idempotency_key"),
        db.CheckConstraint("status IN ('pending','completed','expired')", name="status_valid"),
    )


class WebhookEventRecord(db.Model):
    __tablename__ = "billing_webhook_events"

    provider = db.Column(db.String(30), primary_key=True)
    event_id = db.Column(db.String(128), primary_key=True)
    event_type = db.Column(db.String(60), nullable=False)
    outcome = db.Column(db.String(20), nullable=False, default="applied")
    received_at = created_at_column()
