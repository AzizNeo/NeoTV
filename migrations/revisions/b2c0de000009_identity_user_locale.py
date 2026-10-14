"""identity: preferred language

Revision ID: b2c0de000009
Revises: b2c0de000008
Create Date: 2026-10-14

The user's interface and e-mail language (NULL = negotiated from the browser / default). Additive, nullable.

Rules: one module per revision; never edit a revision that has shipped;
data migrations use SQLAlchemy Core only (never import app models — they
change, this file must not).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = 'b2c0de000009'
down_revision = 'b2c0de000008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('identity_users') as batch_op:
        batch_op.add_column(sa.Column('locale', sa.String(length=8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('identity_users') as batch_op:
        batch_op.drop_column('locale')
