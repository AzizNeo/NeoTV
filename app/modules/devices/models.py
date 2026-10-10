from __future__ import annotations

from app.kernel.db import UTCDateTime, created_at_column, db


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)  # soft reference
    device_key = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    device_type = db.Column(db.String(20), nullable=False, default="desktop")
    browser = db.Column(db.String(50))
    os = db.Column(db.String(50))
    is_trusted = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    login_count = db.Column(db.Integer, nullable=False, default=1)
    last_ip = db.Column(db.String(45))
    last_seen_at = db.Column(UTCDateTime(), nullable=False)
    created_at = created_at_column()

    __table_args__ = (db.UniqueConstraint("user_id", "device_key", name="uq_devices_user_id_device_key"),)
