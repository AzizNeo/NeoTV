"""App credentials for Xtream-compatible TV apps."""

from __future__ import annotations

from app.kernel.db import UTCDateTime, created_at_column, db


class XtreamCredential(db.Model):
    __tablename__ = "xtream_credentials"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)  # soft reference to identity (no FK across modules)
    profile_id = db.Column(db.Integer, nullable=False, index=True)  # soft reference to profile
    label = db.Column(db.String(40), nullable=False)
    username = db.Column(db.String(16), nullable=False, unique=True)  # revoked names are never reused
    secret_hash = db.Column(db.String(64), nullable=False)
    created_at = created_at_column()
    last_used_at = db.Column(UTCDateTime())
    revoked_at = db.Column(UTCDateTime())
