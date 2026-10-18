"""xtream: app credentials and category ids for Xtream-compatible TV apps

Revision ID: b2c0de000012
Revises: b2c0de000011
Create Date: 2026-10-18

New optional module: one row per app credential (soft references to the user and the profile, no FK
across modules). Revoked rows stay so their usernames are never handed out again. Plus a stable
numeric id per category name (Xtream apps key categories by number). Purely additive.

Rules: one module per revision; never edit a revision that has shipped;
data migrations use SQLAlchemy Core only (never import app models — they
change, this file must not).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = 'b2c0de000012'
down_revision = 'b2c0de000011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'xtream_credentials',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=40), nullable=False),
        sa.Column('username', sa.String(length=16), nullable=False),
        sa.Column('secret_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('username', name=op.f('uq_xtream_credentials_username')),
    )
    op.create_index(op.f('ix_xtream_credentials_user_id'), 'xtream_credentials', ['user_id'])
    op.create_index(op.f('ix_xtream_credentials_profile_id'), 'xtream_credentials', ['profile_id'])
    op.create_table(
        'xtream_categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('section', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.UniqueConstraint('section', 'name', name=op.f('uq_xtream_categories_section_name')),
        sa.CheckConstraint("section IN ('live','vod','series')", name=op.f('ck_xtream_categories_section_valid')),
    )


def downgrade() -> None:
    op.drop_table('xtream_categories')
    op.drop_index(op.f('ix_xtream_credentials_profile_id'), table_name='xtream_credentials')
    op.drop_index(op.f('ix_xtream_credentials_user_id'), table_name='xtream_credentials')
    op.drop_table('xtream_credentials')
