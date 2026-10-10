"""notifications: outbound e-mail table

Revision ID: b2c0de000004
Revises: b2c0de000003
Create Date: 2026-10-10

Rules: one module per revision; never edit a revision that has shipped.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c0de000004"
down_revision = "b2c0de000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications_emails",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("to_address", sa.String(length=254), nullable=False),
        sa.Column("template", sa.String(length=100), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued','sent','failed')", name=op.f("ck_notifications_emails_status_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications_emails")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notifications_emails_dedupe_key")),
    )
    with op.batch_alter_table("notifications_emails") as batch_op:
        batch_op.create_index(batch_op.f("ix_notifications_emails_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_notifications_emails_to_address"), ["to_address"], unique=False)


def downgrade() -> None:
    op.drop_table("notifications_emails")
