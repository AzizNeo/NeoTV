from __future__ import annotations

import uuid

from app.kernel.db import UTCDateTime, created_at_column, db
from app.kernel.time import utcnow


class OutboxStatus:
    PENDING = "pending"
    DISPATCHING = "dispatching"
    DISPATCHED = "dispatched"
    NO_CONSUMER = "no_consumer"


class OutboxRecord(db.Model):
    __tablename__ = "kernel_outbox"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_name = db.Column(db.String(100), nullable=False)
    event_version = db.Column(db.Integer, nullable=False)
    payload_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=OutboxStatus.PENDING)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)
    claimed_at = db.Column(UTCDateTime())
    dispatched_at = db.Column(UTCDateTime())
    created_at = created_at_column()

    __table_args__ = (db.Index("ix_kernel_outbox_status_available", "status", "available_at"),)


class InboxRecord(db.Model):
    """'Consumer X has applied event Y' — written in the SAME transaction as the effect."""

    __tablename__ = "kernel_inbox"

    event_id = db.Column(db.String(36), primary_key=True)
    consumer = db.Column(db.String(120), primary_key=True)
    processed_at = created_at_column()


class DeadLetter(db.Model):
    __tablename__ = "kernel_dead_letters"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(36), nullable=False, index=True)
    consumer = db.Column(db.String(120), nullable=False)
    error = db.Column(db.Text, nullable=False)
    failed_at = created_at_column()
    resolved_at = db.Column(UTCDateTime())

    __table_args__ = (db.UniqueConstraint("event_id", "consumer"),)
