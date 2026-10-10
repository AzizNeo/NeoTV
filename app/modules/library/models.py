from __future__ import annotations

from app.kernel.db import UTCDateTime, created_at_column, db, updated_at_column


class Favorite(db.Model):
    __tablename__ = "library_favorites"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)  # soft reference (identity)
    profile_id = db.Column(db.Integer, nullable=False)  # soft reference (profile)
    content_ref = db.Column(db.String(64), nullable=False)
    created_at = created_at_column()

    __table_args__ = (
        db.UniqueConstraint("profile_id", "content_ref", name="uq_library_favorites_profile_id_content_ref"),
        db.Index("ix_library_favorites_profile_created", "profile_id", "created_at"),
        db.Index("ix_library_favorites_content_ref", "content_ref"),
    )


class Progress(db.Model):
    __tablename__ = "library_progress"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    profile_id = db.Column(db.Integer, nullable=False)
    content_ref = db.Column(db.String(64), nullable=False)
    position_s = db.Column(db.Integer, nullable=False, default=0)
    duration_s = db.Column(db.Integer, nullable=False, default=0)
    ratio = db.Column(db.Float, nullable=False, default=0.0)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = created_at_column()
    updated_at = updated_at_column()

    __table_args__ = (
        db.UniqueConstraint("profile_id", "content_ref", name="uq_library_progress_profile_id_content_ref"),
        db.CheckConstraint("position_s >= 0 AND duration_s >= 0", name="non_negative"),
        db.CheckConstraint("ratio >= 0 AND ratio <= 1", name="ratio_range"),
        db.Index("ix_library_progress_profile_completed_updated", "profile_id", "completed", "updated_at"),
        db.Index("ix_library_progress_content_ref", "content_ref"),
    )


class HistoryEntry(db.Model):
    __tablename__ = "library_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    profile_id = db.Column(db.Integer, nullable=False)
    content_ref = db.Column(db.String(64), nullable=False)
    session_token = db.Column(db.String(64), unique=True)  # idempotency for event redelivery
    watched_seconds = db.Column(db.Integer, nullable=False, default=0)
    watched_at = db.Column(UTCDateTime(), nullable=False)

    __table_args__ = (
        db.Index("ix_library_history_profile_watched", "profile_id", "watched_at"),
        db.Index("ix_library_history_content_ref", "content_ref"),
    )
