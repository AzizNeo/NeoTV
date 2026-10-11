"""titles: storefront metadata

Revision ID: b2c0de000007
Revises: b2c0de000006
Create Date: 2026-10-11

New optional module: titles, genres, seasons, episodes. Purely additive — no
existing table is touched, so the downgrade only drops what this revision created.

Rules: one module per revision; never edit a revision that has shipped;
data migrations use SQLAlchemy Core only (never import app models — they
change, this file must not).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = 'b2c0de000007'
down_revision = 'b2c0de000006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('titles_genres',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_titles_genres')),
    sa.UniqueConstraint('slug', name=op.f('uq_titles_genres_slug'))
    )
    op.create_table('titles_titles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('synopsis', sa.Text(), nullable=True),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('runtime_minutes', sa.Integer(), nullable=True),
    sa.Column('rating', sa.String(length=10), nullable=False),
    sa.Column('poster_url', sa.String(length=1024), nullable=True),
    sa.Column('backdrop_url', sa.String(length=1024), nullable=True),
    sa.Column('play_ref', sa.String(length=64), nullable=True),
    sa.Column('featured_rank', sa.Integer(), nullable=True),
    sa.Column('is_published', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind = 'movie' OR play_ref IS NULL", name=op.f('ck_titles_titles_series_no_play_ref')),
    sa.CheckConstraint("kind IN ('movie','series')", name=op.f('ck_titles_titles_kind_valid')),
    sa.CheckConstraint("rating IN ('general','teen','adult','unrated')", name=op.f('ck_titles_titles_rating_valid')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_titles_titles')),
    sa.UniqueConstraint('slug', name=op.f('uq_titles_titles_slug'))
    )
    with op.batch_alter_table('titles_titles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_titles_titles_play_ref'), ['play_ref'], unique=False)
        batch_op.create_index('ix_titles_titles_published_featured', ['is_published', 'featured_rank'], unique=False)
        batch_op.create_index(batch_op.f('ix_titles_titles_year'), ['year'], unique=False)

    op.create_table('titles_seasons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title_id', sa.Integer(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['title_id'], ['titles_titles.id'], name=op.f('fk_titles_seasons_title_id_titles_titles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_titles_seasons')),
    sa.UniqueConstraint('title_id', 'number', name='uq_titles_seasons_title_id_number')
    )
    op.create_table('titles_title_genres',
    sa.Column('title_id', sa.Integer(), nullable=False),
    sa.Column('genre_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['genre_id'], ['titles_genres.id'], name=op.f('fk_titles_title_genres_genre_id_titles_genres'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['title_id'], ['titles_titles.id'], name=op.f('fk_titles_title_genres_title_id_titles_titles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('title_id', 'genre_id', name=op.f('pk_titles_title_genres'))
    )
    op.create_table('titles_episodes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('synopsis', sa.Text(), nullable=True),
    sa.Column('runtime_minutes', sa.Integer(), nullable=True),
    sa.Column('still_url', sa.String(length=1024), nullable=True),
    sa.Column('play_ref', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['season_id'], ['titles_seasons.id'], name=op.f('fk_titles_episodes_season_id_titles_seasons'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_titles_episodes')),
    sa.UniqueConstraint('season_id', 'number', name='uq_titles_episodes_season_id_number')
    )
    with op.batch_alter_table('titles_episodes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_titles_episodes_play_ref'), ['play_ref'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('titles_episodes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_titles_episodes_play_ref'))

    op.drop_table('titles_episodes')
    op.drop_table('titles_title_genres')
    op.drop_table('titles_seasons')
    with op.batch_alter_table('titles_titles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_titles_titles_year'))
        batch_op.drop_index('ix_titles_titles_published_featured')
        batch_op.drop_index(batch_op.f('ix_titles_titles_play_ref'))

    op.drop_table('titles_titles')
    op.drop_table('titles_genres')
