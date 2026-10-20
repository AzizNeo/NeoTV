"""live: catch-up archive settings per channel (ADR-0012)

Revision ID: b2c0de000013
Revises: b2c0de000012
Create Date: 2026-10-20

archive_days (0 = off, the default for every existing channel) and, for external sources, who
confirmed the operator may record the stream and when. Purely additive.

Rules: one module per revision; never edit a revision that has shipped;
data migrations use SQLAlchemy Core only (never import app models — they
change, this file must not).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = 'b2c0de000013'
down_revision = 'b2c0de000012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('live_channels') as batch_op:
        batch_op.add_column(sa.Column('archive_days', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('archive_confirmed_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('archive_confirmed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint(op.f('ck_live_channels_archive_days_valid'), sa.text('archive_days >= 0'))


def downgrade() -> None:
    with op.batch_alter_table('live_channels') as batch_op:
        batch_op.drop_constraint(op.f('ck_live_channels_archive_days_valid'), type_='check')
        batch_op.drop_column('archive_confirmed_at')
        batch_op.drop_column('archive_confirmed_by')
        batch_op.drop_column('archive_days')
