from __future__ import annotations

from app.kernel.db import UTCDateTime, created_at_column, db, updated_at_column


class Playlist(db.Model):
    __tablename__ = "catalog_playlists"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    source_url = db.Column(db.String(1024))  # may embed provider credentials → never returned by public APIs
    is_system = db.Column(db.Boolean, nullable=False, default=False)  # bucket for manual imports
    created_by = db.Column(db.Integer)  # soft reference to identity user
    last_synced_at = db.Column(UTCDateTime())
    last_sync_status = db.Column(db.String(20))
    last_sync_error = db.Column(db.String(500))
    created_at = created_at_column()
    updated_at = updated_at_column()


class Channel(db.Model):
    __tablename__ = "catalog_channels"

    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(
        db.Integer, db.ForeignKey("catalog_playlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_key = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(256), nullable=False)
    stream_url = db.Column(db.String(1024), nullable=False)
    logo_url = db.Column(db.String(1024))
    group_name = db.Column(db.String(128), nullable=False, default="Uncategorized", index=True)
    kind = db.Column(db.String(10), nullable=False, default="live")
    rating = db.Column(db.String(10), nullable=False, default="unrated")
    delivery = db.Column(db.String(10), nullable=False, default="proxy")
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = created_at_column()
    updated_at = updated_at_column()

    __table_args__ = (
        db.UniqueConstraint("playlist_id", "source_key", name="uq_catalog_channels_playlist_id_source_key"),
        db.CheckConstraint("kind IN ('live','vod')", name="kind"),
        db.CheckConstraint("rating IN ('general','teen','adult','unrated')", name="rating"),
        db.CheckConstraint("delivery IN ('proxy','direct')", name="delivery"),
    )
