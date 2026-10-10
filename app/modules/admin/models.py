from __future__ import annotations

from sqlalchemy import text

from app.kernel.db import UTCDateTime, db


class LoginSignal(db.Model):
    """Read model fed by ``identity.user_logged_in`` (pruned after 7 days)."""

    __tablename__ = "admin_login_signals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    ip = db.Column(db.String(45), nullable=False)
    device_hash = db.Column(db.String(32), nullable=False)
    occurred_at = db.Column(UTCDateTime(), nullable=False)

    __table_args__ = (
        db.Index("ix_admin_login_signals_user_occurred", "user_id", "occurred_at"),
        db.Index("ix_admin_login_signals_occurred", "occurred_at"),
    )


class AbuseFlag(db.Model):
    __tablename__ = "admin_abuse_flags"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    details = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open")
    first_seen_at = db.Column(UTCDateTime(), nullable=False)
    last_seen_at = db.Column(UTCDateTime(), nullable=False)
    resolved_by = db.Column(db.Integer)
    resolved_at = db.Column(UTCDateTime())

    __table_args__ = (
        db.CheckConstraint("status IN ('open','dismissed','actioned')", name="status_valid"),
        db.Index(
            "uq_admin_abuse_flags_open",
            "user_id",
            "kind",
            unique=True,
            sqlite_where=text("status = 'open'"),
            postgresql_where=text("status = 'open'"),
        ),
        db.Index("ix_admin_abuse_flags_status_last_seen", "status", "last_seen_at"),
    )
