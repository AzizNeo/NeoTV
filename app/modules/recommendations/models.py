from __future__ import annotations

from app.kernel.db import UTCDateTime, db


class PlayBucket(db.Model):
    """Plays per content per hour (global popularity)."""

    __tablename__ = "reco_play_buckets"

    content_ref = db.Column(db.String(64), primary_key=True)
    bucket = db.Column(UTCDateTime(), primary_key=True)  # truncated to the hour
    plays = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (db.Index("ix_reco_play_buckets_bucket", "bucket"),)


class ProfileAffinity(db.Model):
    """What a profile plays, how often and how recently."""

    __tablename__ = "reco_profile_affinity"

    profile_id = db.Column(db.Integer, primary_key=True)
    content_ref = db.Column(db.String(64), primary_key=True)
    plays = db.Column(db.Integer, nullable=False, default=0)
    last_played_at = db.Column(UTCDateTime(), nullable=False)

    __table_args__ = (db.Index("ix_reco_profile_affinity_profile_last", "profile_id", "last_played_at"),)
