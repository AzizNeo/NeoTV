from __future__ import annotations

from app.kernel.db import created_at_column, db


class TemplateItem(db.Model):
    __tablename__ = "_template_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)  # soft reference (identity)
    title = db.Column(db.String(120), nullable=False)
    created_at = created_at_column()
