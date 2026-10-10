from __future__ import annotations

from sqlalchemy import text

from app.kernel.db import UTCDateTime, created_at_column, db, updated_at_column


class DrmPolicy(db.Model):
    """Content-level playback restrictions. Account-level limits (streams,
    resolution ceiling, offline) come from billing entitlements — the policy can
    only tighten them, never widen them (single source of truth, DATA-03)."""

    __tablename__ = "drm_policies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    max_resolution = db.Column(db.String(10), nullable=False, default="2160p")
    license_duration_s = db.Column(db.Integer, nullable=False, default=600)
    allow_offline = db.Column(db.Boolean, nullable=False, default=False)
    offline_validity_h = db.Column(db.Integer, nullable=False, default=48)
    allowed_device_classes = db.Column(db.String(100))  # CSV; NULL = any
    require_hdcp = db.Column(db.Boolean, nullable=False, default=False)
    allow_screen_capture = db.Column(db.Boolean, nullable=False, default=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    created_at = created_at_column()
    updated_at = updated_at_column()

    __table_args__ = (
        db.CheckConstraint("license_duration_s BETWEEN 60 AND 86400", name="license_duration_range"),
        db.CheckConstraint("offline_validity_h BETWEEN 1 AND 720", name="offline_validity_range"),
        db.Index(
            "uq_drm_policies_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default"),
        ),
    )


class DrmContent(db.Model):
    __tablename__ = "drm_contents"

    id = db.Column(db.Integer, primary_key=True)
    content_ref = db.Column(db.String(64), nullable=False, unique=True)  # soft reference (ContentRef)
    key_id = db.Column(db.String(32), nullable=False, unique=True)  # 16-byte KID, hex
    wrapped_key = db.Column(db.Text, nullable=False)  # KeyVault envelope, never the clear key
    systems = db.Column(db.String(100), nullable=False)  # CSV of DrmSystem
    policy_id = db.Column(db.Integer, db.ForeignKey("drm_policies.id", ondelete="RESTRICT"), index=True)
    key_rotated_at = db.Column(UTCDateTime())
    created_at = created_at_column()
    updated_at = updated_at_column()


class DrmLicense(db.Model):
    """One license per (playback session, system); renewals extend it. Concurrency
    is enforced by the playback session slot, not by counting licenses (DATA-02)."""

    __tablename__ = "drm_licenses"

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    session_token = db.Column(db.String(64), nullable=False)
    content_ref = db.Column(db.String(64), nullable=False)
    key_id = db.Column(db.String(32), nullable=False)
    system = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")
    max_resolution = db.Column(db.String(10))
    renewals = db.Column(db.Integer, nullable=False, default=0)
    ip = db.Column(db.String(45))
    issued_at = db.Column(UTCDateTime(), nullable=False)
    expires_at = db.Column(UTCDateTime(), nullable=False)
    ended_at = db.Column(UTCDateTime())

    __table_args__ = (
        db.UniqueConstraint("session_token", "system", name="uq_drm_licenses_session_token_system"),
        db.CheckConstraint("status IN ('active','released','revoked','expired')", name="status_valid"),
        db.Index("ix_drm_licenses_status_expires", "status", "expires_at"),
        db.Index("ix_drm_licenses_content_status", "content_ref", "status"),
        db.Index("ix_drm_licenses_user_status", "user_id", "status"),
    )


class DrmEvent(db.Model):
    """Append-only audit trail (purged by retention task)."""

    __tablename__ = "drm_events"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(30), nullable=False)
    user_id = db.Column(db.Integer)
    content_ref = db.Column(db.String(64))
    license_id = db.Column(db.String(32))
    system = db.Column(db.String(20))
    error_code = db.Column(db.String(50))
    detail = db.Column(db.String(255))
    ip = db.Column(db.String(45))
    created_at = created_at_column()

    __table_args__ = (
        db.Index("ix_drm_events_type_created", "event_type", "created_at"),
        db.Index("ix_drm_events_user_created", "user_id", "created_at"),
    )
