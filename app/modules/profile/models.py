from __future__ import annotations

from sqlalchemy import text

from app.kernel.db import created_at_column, db


class Profile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)  # soft reference (module boundary)
    name = db.Column(db.String(40), nullable=False)
    avatar = db.Column(db.String(32), nullable=False, default="default")
    is_kids = db.Column(db.Boolean, nullable=False, default=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    pin_hash = db.Column(db.String(255))
    created_at = created_at_column()

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_profiles_user_id_name"),
        db.Index(
            "ux_profiles_user_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default = 1"),
        ),
    )
