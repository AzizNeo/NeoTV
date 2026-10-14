from __future__ import annotations

import uuid

from app.kernel.db import UTCDateTime, created_at_column, db


class EmailMessage(db.Model):
    """One outbound mail. ``context_json`` may hold secrets (one-time links), so it
    is cleared as soon as the message is sent or permanently failed (and by the
    ``notifications.redact_stale`` sweep); only metadata is retained."""

    __tablename__ = "notifications_emails"
    __table_args__ = (db.CheckConstraint("status IN ('queued','sent','failed')", name="status_valid"),)

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    to_address = db.Column(db.String(254), nullable=False, index=True)
    template = db.Column(db.String(100), nullable=False)
    context_json = db.Column(db.Text)
    dedupe_key = db.Column(db.String(200), unique=True)
    locale = db.Column(db.String(8))  # recipient's language at queue time; NULL → default
    status = db.Column(db.String(10), nullable=False, default="queued", index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(500))
    created_at = created_at_column()
    sent_at = db.Column(UTCDateTime())
