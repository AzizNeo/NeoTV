"""titles: translated texts

Revision ID: b2c0de000010
Revises: b2c0de000009
Create Date: 2026-10-14

Translations of titles, episodes and genres (one row per owner and locale; the base columns
keep the default-locale original). Purely additive.

Rules: one module per revision; never edit a revision that has shipped;
data migrations use SQLAlchemy Core only (never import app models — they
change, this file must not).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = 'b2c0de000010'
down_revision = 'b2c0de000009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'titles_title_texts',
        sa.Column('title_id', sa.Integer(), sa.ForeignKey('titles_titles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('locale', sa.String(length=8), primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('synopsis', sa.Text(), nullable=True),
    )
    op.create_table(
        'titles_episode_texts',
        sa.Column('episode_id', sa.Integer(), sa.ForeignKey('titles_episodes.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('locale', sa.String(length=8), primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('synopsis', sa.Text(), nullable=True),
    )
    op.create_table(
        'titles_genre_texts',
        sa.Column('genre_id', sa.Integer(), sa.ForeignKey('titles_genres.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('locale', sa.String(length=8), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('titles_genre_texts')
    op.drop_table('titles_episode_texts')
    op.drop_table('titles_title_texts')
