"""v2 contract: drop the legacy tables

Revision ID: b2c0de000003
Revises: b2c0de000002
Create Date: 2026-10-09

Contract step. Run only after verifying b2c0de000002's copy (its log lists
per-table copied/skipped counts). Irreversible by design: the legacy schema
is not recreated on downgrade (restore the pre-upgrade backup instead —
``python -m tools.devctl db-backup`` is run by ``devctl migrate``).
"""

from __future__ import annotations

from alembic import op

revision = "b2c0de000003"
down_revision = "b2c0de000002"
branch_labels = None
depends_on = None

# Children before parents (legacy FKs).
LEGACY_TABLES = (
    "access_log",
    "background_job",
    "drm_license",
    "drm_event",
    "drm_content",
    "drm_policy",
    "favorite",
    "watch_history",
    "watch_progress",
    "playback_event",
    "playback_metrics",
    "stream_session",
    "device",
    "subscription",
    "legacy_live_epg",
    "live_channel",
    "channel",
    "playlist",
    "user",
)


def upgrade() -> None:
    for index, table in (
        ("idx_channel_created", "playback_event"),
        ("idx_user_channel_event", "playback_event"),
        ("idx_drm_event_type_time", "drm_event"),
        ("idx_drm_event_user_time", "drm_event"),
    ):
        op.drop_index(index, table_name=table, if_exists=True)
    for table in LEGACY_TABLES:
        op.drop_table(table, if_exists=True)


def downgrade() -> None:
    raise RuntimeError(
        "b2c0de000003 is a contract step and cannot be reversed; restore the pre-upgrade database backup."
    )
