from __future__ import annotations

from app.kernel.db import UTCDateTime, created_at_column, db, updated_at_column


class LiveChannel(db.Model):
    __tablename__ = "live_channels"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    logo_url = db.Column(db.String(1024))
    source_type = db.Column(db.String(10), nullable=False, default="external")  # external | ingest
    upstream_url = db.Column(db.String(1024))  # external sources only — never exposed publicly
    delivery = db.Column(db.String(10), nullable=False, default="proxy")  # proxy | direct (external only)
    playback_id = db.Column(db.String(32), nullable=False, unique=True)  # public, random, NOT the ingest key
    ingest_key_hash = db.Column(db.String(64), unique=True)
    ingest_key_last4 = db.Column(db.String(4))
    epg_channel_id = db.Column(db.String(128), index=True)  # XMLTV <channel id>
    rating = db.Column(db.String(10), nullable=False, default="unrated")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_live = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    started_at = db.Column(UTCDateTime())
    created_at = created_at_column()
    updated_at = updated_at_column()

    __table_args__ = (
        db.CheckConstraint("source_type IN ('external','ingest')", name="source_type"),
        db.CheckConstraint("delivery IN ('proxy','direct')", name="delivery"),
        db.CheckConstraint("rating IN ('general','teen','adult','unrated')", name="rating"),
        db.CheckConstraint(
            "(source_type = 'external' AND upstream_url IS NOT NULL) OR source_type = 'ingest'",
            name="external_has_upstream",
        ),
    )


class LiveProgram(db.Model):
    __tablename__ = "live_epg"

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("live_channels.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(1000))
    starts_at = db.Column(UTCDateTime(), nullable=False)
    ends_at = db.Column(UTCDateTime(), nullable=False)

    __table_args__ = (
        db.Index("ix_live_epg_channel_starts", "channel_id", "starts_at"),
        db.UniqueConstraint("channel_id", "starts_at", name="uq_live_epg_channel_id_starts_at"),
        db.CheckConstraint("ends_at > starts_at", name="time_order"),
    )
