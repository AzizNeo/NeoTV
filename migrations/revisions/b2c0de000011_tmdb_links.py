"""tmdb: links between titles and TMDB entries

Revision ID: b2c0de000011
Revises: b2c0de000010
Create Date: 2026-10-15

New optional module: one row per title imported from TMDB (soft reference by slug, no FK
across modules). Purely additive.

Rules: one module per revision; never edit a revision that has shipped;
data migrations use SQLAlchemy Core only (never import app models — they
change, this file must not).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = 'b2c0de000011'
down_revision = 'b2c0de000010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tmdb_links',
        sa.Column('title_slug', sa.String(length=80), primary_key=True),
        sa.Column('tmdb_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('movie','series')", name=op.f('ck_tmdb_links_kind_valid')),
    )
    op.create_index(op.f('ix_tmdb_links_tmdb_id'), 'tmdb_links', ['tmdb_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_tmdb_links_tmdb_id'), table_name='tmdb_links')
    op.drop_table('tmdb_links')
