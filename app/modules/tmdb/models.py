"""Which titles were imported from which TMDB entry (for refresh and for the admin UI)."""

from __future__ import annotations

from app.kernel.db import UTCDateTime, db


class TmdbLink(db.Model):
    __tablename__ = "tmdb_links"
    __table_args__ = (db.CheckConstraint("kind IN ('movie','series')", name="kind_valid"),)

    title_slug = db.Column(db.String(80), primary_key=True)  # soft reference to titles (no FK across modules)
    tmdb_id = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    synced_at = db.Column(UTCDateTime(), nullable=False)
