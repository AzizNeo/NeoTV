"""identity: e-mail verification state and one-time action tokens

Revision ID: b2c0de000005
Revises: b2c0de000004
Create Date: 2026-10-10

Rules: one module per revision; never edit a revision that has shipped.
Existing accounts start unverified (``email_verified_at`` NULL) — they verify
on demand from the account page; nothing is backfilled on purpose.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c0de000005"
down_revision = "b2c0de000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("identity_users") as batch_op:
        batch_op.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "identity_action_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('verify_email','reset_password')", name=op.f("ck_identity_action_tokens_purpose_valid")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity_users.id"],
            name=op.f("fk_identity_action_tokens_user_id_identity_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_action_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_identity_action_tokens_token_hash")),
    )
    with op.batch_alter_table("identity_action_tokens") as batch_op:
        batch_op.create_index("ix_identity_action_tokens_user_purpose", ["user_id", "purpose"], unique=False)


def downgrade() -> None:
    op.drop_table("identity_action_tokens")
    with op.batch_alter_table("identity_users") as batch_op:
        batch_op.drop_column("email_verified_at")
