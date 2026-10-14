from __future__ import annotations

import uuid

from app.kernel.db import UTCDateTime, created_at_column, db
from app.modules.identity.domain import role_grants


class User(db.Model):
    """Also satisfies the kernel ``Principal`` protocol."""

    __tablename__ = "identity_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, unique=True)
    email = db.Column(db.String(254), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    token_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = created_at_column()
    last_login_at = db.Column(UTCDateTime())
    last_login_ip = db.Column(db.String(45))
    email_verified_at = db.Column(UTCDateTime())
    locale = db.Column(db.String(8))  # interface + e-mail language; NULL → negotiated / default

    # ── Principal protocol ────────────────────────────────────────────────
    @property
    def is_authenticated(self) -> bool:
        return True

    def has_permission(self, permission: str) -> bool:
        return bool(self.is_active) and role_grants(self.role, permission)


class RefreshToken(db.Model):
    """Opaque rotating refresh token (stored hashed). One *family* per login;
    presenting an already-rotated member revokes the whole family."""

    __tablename__ = "identity_refresh_tokens"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id = db.Column(db.String(36), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    device_key = db.Column(db.String(40), index=True)
    user_agent = db.Column(db.String(255))
    ip = db.Column(db.String(45))
    created_at = created_at_column()
    expires_at = db.Column(UTCDateTime(), nullable=False)
    rotated_at = db.Column(UTCDateTime())
    revoked_at = db.Column(UTCDateTime())


class ActionToken(db.Model):
    """One-time link (e-mail verification, password reset, e-mail change and its undo). Only the SHA-256 of
    the secret is stored; ``email`` pins the address the link was sent to, so a
    link stops working if the account's address changes."""

    __tablename__ = "identity_action_tokens"
    __table_args__ = (
        db.CheckConstraint(
            "purpose IN ('verify_email','reset_password','change_email','revert_email')", name="purpose_valid"
        ),
        db.Index("ix_identity_action_tokens_user_purpose", "user_id", "purpose"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False)
    purpose = db.Column(db.String(20), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    email = db.Column(db.String(254), nullable=False)
    created_at = created_at_column()
    expires_at = db.Column(UTCDateTime(), nullable=False)
    used_at = db.Column(UTCDateTime())
