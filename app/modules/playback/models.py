from __future__ import annotations

from app.kernel.db import UTCDateTime, created_at_column, db


class PlaybackSessionRecord(db.Model):
    """Audit trail. The *source of truth* for concurrency is the Redis slot set."""

    __tablename__ = "playback_sessions"

    token = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    profile_id = db.Column(db.Integer, nullable=False)
    content_ref = db.Column(db.String(64), nullable=False, index=True)
    device_key = db.Column(db.String(40), nullable=False)
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    started_at = created_at_column()
    last_heartbeat_at = db.Column(UTCDateTime(), nullable=False)
    ended_at = db.Column(UTCDateTime(), index=True)
    end_reason = db.Column(db.String(20))


class PlaybackEventRecord(db.Model):
    __tablename__ = "playback_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    profile_id = db.Column(db.Integer, nullable=False)
    content_ref = db.Column(db.String(64), nullable=False)
    event_type = db.Column(db.String(16), nullable=False)
    position_s = db.Column(db.Integer, nullable=False, default=0)
    session_token = db.Column(db.String(64))
    created_at = created_at_column()

    __table_args__ = (
        db.Index("ix_playback_events_ref_created", "content_ref", "created_at"),
        db.Index("ix_playback_events_profile_created", "profile_id", "created_at"),
    )


class QoeRecord(db.Model):
    __tablename__ = "playback_qoe"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    content_ref = db.Column(db.String(64), nullable=False)
    session_token = db.Column(db.String(64))
    startup_time_ms = db.Column(db.Integer)
    rebuffer_count = db.Column(db.Integer, nullable=False, default=0)
    rebuffer_duration_ms = db.Column(db.Integer, nullable=False, default=0)
    watch_duration_s = db.Column(db.Integer, nullable=False, default=0)
    bitrate_kbps = db.Column(db.Integer)
    resolution = db.Column(db.String(20))
    device_type = db.Column(db.String(20))
    connection_type = db.Column(db.String(20))
    created_at = created_at_column()
