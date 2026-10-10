"""v2 schema: kernel + modular tables (expand step, no data movement)

Revision ID: b2c0de000001
Revises: d88aab850aa0
Create Date: 2026-10-09

Expand / migrate / contract cut-over from the legacy schema:

* b2c0de000001 (this file) — creates every v2 table next to the legacy ones.
  The only legacy object touched is ``live_epg`` (renamed to
  ``legacy_live_epg``) because the v2 live module owns a table of that name.
* b2c0de000002 — copies and transforms the legacy data.
* b2c0de000003 — drops the legacy tables.

Operators can stop at b2c0de000002 (``flask db upgrade b2c0de000002``), verify
the copied data, then contract. Each module's tables are created by their own
function, in module dependency order; new tables of a module go into *new*
revisions named ``<date>_<module>_<change>.py`` — this file is never edited.
"""

from __future__ import annotations

from collections.abc import Callable

import sqlalchemy as sa
from alembic import op

revision = "b2c0de000001"
down_revision = "d88aab850aa0"
branch_labels = None
depends_on = None


def _create_kernel() -> None:
    op.create_table(
        "kernel_dead_letters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("consumer", sa.String(length=120), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kernel_dead_letters")),
        sa.UniqueConstraint(
            "event_id",
            "consumer",
            name=op.f("uq_kernel_dead_letters_event_id_consumer"),
        ),
    )
    op.create_index(
        op.f("ix_kernel_dead_letters_event_id"),
        "kernel_dead_letters",
        ["event_id"],
        unique=False,
    )
    op.create_table(
        "kernel_inbox",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("consumer", sa.String(length=120), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "consumer", name=op.f("pk_kernel_inbox")),
    )
    op.create_table(
        "kernel_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_name", sa.String(length=100), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kernel_outbox")),
    )
    op.create_index(
        "ix_kernel_outbox_status_available",
        "kernel_outbox",
        ["status", "available_at"],
        unique=False,
    )


def _create_identity() -> None:
    op.create_table(
        "identity_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_ip", sa.String(length=45), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_users")),
        sa.UniqueConstraint("email", name=op.f("uq_identity_users_email")),
        sa.UniqueConstraint("username", name=op.f("uq_identity_users_username")),
    )
    op.create_table(
        "identity_refresh_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("device_key", sa.String(length=40), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity_users.id"],
            name=op.f("fk_identity_refresh_tokens_user_id_identity_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_refresh_tokens")),
        sa.UniqueConstraint(
            "token_hash", name=op.f("uq_identity_refresh_tokens_token_hash")
        ),
    )
    op.create_index(
        op.f("ix_identity_refresh_tokens_device_key"),
        "identity_refresh_tokens",
        ["device_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_identity_refresh_tokens_family_id"),
        "identity_refresh_tokens",
        ["family_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_identity_refresh_tokens_user_id"),
        "identity_refresh_tokens",
        ["user_id"],
        unique=False,
    )


def _create_profile() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("avatar", sa.String(length=32), nullable=False),
        sa.Column("is_kids", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("pin_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("user_id", "name", name="uq_profiles_user_id_name"),
    )
    op.create_index(op.f("ix_profiles_user_id"), "profiles", ["user_id"], unique=False)
    op.create_index(
        "ux_profiles_user_default",
        "profiles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )


def _create_devices() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("device_type", sa.String(length=20), nullable=False),
        sa.Column("browser", sa.String(length=50), nullable=True),
        sa.Column("os", sa.String(length=50), nullable=True),
        sa.Column("is_trusted", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("login_count", sa.Integer(), nullable=False),
        sa.Column("last_ip", sa.String(length=45), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint(
            "user_id", "device_key", name="uq_devices_user_id_device_key"
        ),
    )
    op.create_index(op.f("ix_devices_user_id"), "devices", ["user_id"], unique=False)


def _create_catalog() -> None:
    op.create_table(
        "catalog_playlists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=20), nullable=True),
        sa.Column("last_sync_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_playlists")),
    )
    op.create_table(
        "catalog_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("playlist_id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("stream_url", sa.String(length=1024), nullable=False),
        sa.Column("logo_url", sa.String(length=1024), nullable=True),
        sa.Column("group_name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("rating", sa.String(length=10), nullable=False),
        sa.Column("delivery", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "delivery IN ('proxy','direct')", name=op.f("ck_catalog_channels_delivery")
        ),
        sa.CheckConstraint(
            "kind IN ('live','vod')", name=op.f("ck_catalog_channels_kind")
        ),
        sa.CheckConstraint(
            "rating IN ('general','teen','adult','unrated')",
            name=op.f("ck_catalog_channels_rating"),
        ),
        sa.ForeignKeyConstraint(
            ["playlist_id"],
            ["catalog_playlists.id"],
            name=op.f("fk_catalog_channels_playlist_id_catalog_playlists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_channels")),
        sa.UniqueConstraint(
            "playlist_id",
            "source_key",
            name="uq_catalog_channels_playlist_id_source_key",
        ),
    )
    op.create_index(
        op.f("ix_catalog_channels_group_name"),
        "catalog_channels",
        ["group_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_catalog_channels_is_active"),
        "catalog_channels",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_catalog_channels_playlist_id"),
        "catalog_channels",
        ["playlist_id"],
        unique=False,
    )


def _create_live() -> None:
    op.create_table(
        "live_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("logo_url", sa.String(length=1024), nullable=True),
        sa.Column("source_type", sa.String(length=10), nullable=False),
        sa.Column("upstream_url", sa.String(length=1024), nullable=True),
        sa.Column("delivery", sa.String(length=10), nullable=False),
        sa.Column("playback_id", sa.String(length=32), nullable=False),
        sa.Column("ingest_key_hash", sa.String(length=64), nullable=True),
        sa.Column("ingest_key_last4", sa.String(length=4), nullable=True),
        sa.Column("epg_channel_id", sa.String(length=128), nullable=True),
        sa.Column("rating", sa.String(length=10), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_live", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(source_type = 'external' AND upstream_url IS NOT NULL) OR source_type = 'ingest'",
            name=op.f("ck_live_channels_external_has_upstream"),
        ),
        sa.CheckConstraint(
            "delivery IN ('proxy','direct')", name=op.f("ck_live_channels_delivery")
        ),
        sa.CheckConstraint(
            "rating IN ('general','teen','adult','unrated')",
            name=op.f("ck_live_channels_rating"),
        ),
        sa.CheckConstraint(
            "source_type IN ('external','ingest')",
            name=op.f("ck_live_channels_source_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_live_channels")),
        sa.UniqueConstraint(
            "ingest_key_hash", name=op.f("uq_live_channels_ingest_key_hash")
        ),
        sa.UniqueConstraint("playback_id", name=op.f("uq_live_channels_playback_id")),
    )
    op.create_index(
        op.f("ix_live_channels_epg_channel_id"),
        "live_channels",
        ["epg_channel_id"],
        unique=False,
    )
    op.create_table(
        "live_epg",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_live_epg_time_order")),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["live_channels.id"],
            name=op.f("fk_live_epg_channel_id_live_channels"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_live_epg")),
        sa.UniqueConstraint(
            "channel_id", "starts_at", name="uq_live_epg_channel_id_starts_at"
        ),
    )
    op.create_index(
        "ix_live_epg_channel_starts",
        "live_epg",
        ["channel_id", "starts_at"],
        unique=False,
    )


def _create_billing() -> None:
    op.create_table(
        "billing_checkouts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("redirect_url", sa.String(length=1000), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','completed','expired')",
            name=op.f("ck_billing_checkouts_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_checkouts")),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_billing_checkouts_user_id_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_billing_checkouts_user_id"),
        "billing_checkouts",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("cycle", sa.String(length=20), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_used", sa.Boolean(), nullable=False),
        sa.Column("grace_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=True),
        sa.Column("external_subscription_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('trial','active','grace','cancelled','expired','suspended')",
            name=op.f("ck_billing_subscriptions_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_subscriptions")),
        sa.UniqueConstraint("user_id", name=op.f("uq_billing_subscriptions_user_id")),
    )
    op.create_index(
        "ix_billing_subscriptions_status_period",
        "billing_subscriptions",
        ["status", "current_period_end"],
        unique=False,
    )
    op.create_table(
        "billing_webhook_events",
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "provider", "event_id", name=op.f("pk_billing_webhook_events")
        ),
    )


def _create_playback() -> None:
    op.create_table(
        "playback_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("position_s", sa.Integer(), nullable=False),
        sa.Column("session_token", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playback_events")),
    )
    op.create_index(
        "ix_playback_events_profile_created",
        "playback_events",
        ["profile_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_playback_events_ref_created",
        "playback_events",
        ["content_ref", "created_at"],
        unique=False,
    )
    op.create_table(
        "playback_qoe",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("session_token", sa.String(length=64), nullable=True),
        sa.Column("startup_time_ms", sa.Integer(), nullable=True),
        sa.Column("rebuffer_count", sa.Integer(), nullable=False),
        sa.Column("rebuffer_duration_ms", sa.Integer(), nullable=False),
        sa.Column("watch_duration_s", sa.Integer(), nullable=False),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=True),
        sa.Column("resolution", sa.String(length=20), nullable=True),
        sa.Column("device_type", sa.String(length=20), nullable=True),
        sa.Column("connection_type", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playback_qoe")),
    )
    op.create_index(
        op.f("ix_playback_qoe_user_id"), "playback_qoe", ["user_id"], unique=False
    )
    op.create_table(
        "playback_sessions",
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("device_key", sa.String(length=40), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("token", name=op.f("pk_playback_sessions")),
    )
    op.create_index(
        op.f("ix_playback_sessions_content_ref"),
        "playback_sessions",
        ["content_ref"],
        unique=False,
    )
    op.create_index(
        op.f("ix_playback_sessions_ended_at"),
        "playback_sessions",
        ["ended_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_playback_sessions_user_id"),
        "playback_sessions",
        ["user_id"],
        unique=False,
    )


def _create_drm() -> None:
    op.create_table(
        "drm_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("content_ref", sa.String(length=64), nullable=True),
        sa.Column("license_id", sa.String(length=32), nullable=True),
        sa.Column("system", sa.String(length=20), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drm_events")),
    )
    op.create_index(
        "ix_drm_events_type_created",
        "drm_events",
        ["event_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_drm_events_user_created",
        "drm_events",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "drm_licenses",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_token", sa.String(length=64), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("key_id", sa.String(length=32), nullable=False),
        sa.Column("system", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("max_resolution", sa.String(length=10), nullable=True),
        sa.Column("renewals", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active','released','revoked','expired')",
            name=op.f("ck_drm_licenses_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drm_licenses")),
        sa.UniqueConstraint(
            "session_token", "system", name="uq_drm_licenses_session_token_system"
        ),
    )
    op.create_index(
        "ix_drm_licenses_content_status",
        "drm_licenses",
        ["content_ref", "status"],
        unique=False,
    )
    op.create_index(
        "ix_drm_licenses_status_expires",
        "drm_licenses",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_drm_licenses_user_status",
        "drm_licenses",
        ["user_id", "status"],
        unique=False,
    )
    op.create_table(
        "drm_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("max_resolution", sa.String(length=10), nullable=False),
        sa.Column("license_duration_s", sa.Integer(), nullable=False),
        sa.Column("allow_offline", sa.Boolean(), nullable=False),
        sa.Column("offline_validity_h", sa.Integer(), nullable=False),
        sa.Column("allowed_device_classes", sa.String(length=100), nullable=True),
        sa.Column("require_hdcp", sa.Boolean(), nullable=False),
        sa.Column("allow_screen_capture", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "license_duration_s BETWEEN 60 AND 86400",
            name=op.f("ck_drm_policies_license_duration_range"),
        ),
        sa.CheckConstraint(
            "offline_validity_h BETWEEN 1 AND 720",
            name=op.f("ck_drm_policies_offline_validity_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drm_policies")),
        sa.UniqueConstraint("name", name=op.f("uq_drm_policies_name")),
    )
    op.create_index(
        "uq_drm_policies_default",
        "drm_policies",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "drm_contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("key_id", sa.String(length=32), nullable=False),
        sa.Column("wrapped_key", sa.Text(), nullable=False),
        sa.Column("systems", sa.String(length=100), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=True),
        sa.Column("key_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["drm_policies.id"],
            name=op.f("fk_drm_contents_policy_id_drm_policies"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drm_contents")),
        sa.UniqueConstraint("content_ref", name=op.f("uq_drm_contents_content_ref")),
        sa.UniqueConstraint("key_id", name=op.f("uq_drm_contents_key_id")),
    )
    op.create_index(
        op.f("ix_drm_contents_policy_id"), "drm_contents", ["policy_id"], unique=False
    )


def _create_library() -> None:
    op.create_table(
        "library_favorites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_favorites")),
        sa.UniqueConstraint(
            "profile_id",
            "content_ref",
            name="uq_library_favorites_profile_id_content_ref",
        ),
    )
    op.create_index(
        "ix_library_favorites_content_ref",
        "library_favorites",
        ["content_ref"],
        unique=False,
    )
    op.create_index(
        "ix_library_favorites_profile_created",
        "library_favorites",
        ["profile_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "library_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("session_token", sa.String(length=64), nullable=True),
        sa.Column("watched_seconds", sa.Integer(), nullable=False),
        sa.Column("watched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_history")),
        sa.UniqueConstraint(
            "session_token", name=op.f("uq_library_history_session_token")
        ),
    )
    op.create_index(
        "ix_library_history_content_ref",
        "library_history",
        ["content_ref"],
        unique=False,
    )
    op.create_index(
        "ix_library_history_profile_watched",
        "library_history",
        ["profile_id", "watched_at"],
        unique=False,
    )
    op.create_table(
        "library_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("position_s", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "position_s >= 0 AND duration_s >= 0",
            name=op.f("ck_library_progress_non_negative"),
        ),
        sa.CheckConstraint(
            "ratio >= 0 AND ratio <= 1", name=op.f("ck_library_progress_ratio_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_progress")),
        sa.UniqueConstraint(
            "profile_id",
            "content_ref",
            name="uq_library_progress_profile_id_content_ref",
        ),
    )
    op.create_index(
        "ix_library_progress_content_ref",
        "library_progress",
        ["content_ref"],
        unique=False,
    )
    op.create_index(
        "ix_library_progress_profile_completed_updated",
        "library_progress",
        ["profile_id", "completed", "updated_at"],
        unique=False,
    )


def _create_recommendations() -> None:
    op.create_table(
        "reco_play_buckets",
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plays", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "content_ref", "bucket", name=op.f("pk_reco_play_buckets")
        ),
    )
    op.create_index(
        "ix_reco_play_buckets_bucket", "reco_play_buckets", ["bucket"], unique=False
    )
    op.create_table(
        "reco_profile_affinity",
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(length=64), nullable=False),
        sa.Column("plays", sa.Integer(), nullable=False),
        sa.Column("last_played_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "profile_id", "content_ref", name=op.f("pk_reco_profile_affinity")
        ),
    )
    op.create_index(
        "ix_reco_profile_affinity_profile_last",
        "reco_profile_affinity",
        ["profile_id", "last_played_at"],
        unique=False,
    )


def _create_admin() -> None:
    op.create_table(
        "admin_abuse_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("details", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open','dismissed','actioned')",
            name=op.f("ck_admin_abuse_flags_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_abuse_flags")),
    )
    op.create_index(
        "ix_admin_abuse_flags_status_last_seen",
        "admin_abuse_flags",
        ["status", "last_seen_at"],
        unique=False,
    )
    op.create_index(
        "uq_admin_abuse_flags_open",
        "admin_abuse_flags",
        ["user_id", "kind"],
        unique=True,
        sqlite_where=sa.text("status = 'open'"),
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "admin_login_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("device_hash", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_login_signals")),
    )
    op.create_index(
        "ix_admin_login_signals_occurred",
        "admin_login_signals",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_login_signals_user_occurred",
        "admin_login_signals",
        ["user_id", "occurred_at"],
        unique=False,
    )


MODULE_TABLES: dict[str, tuple[str, ...]] = {
    "kernel": ("kernel_dead_letters", "kernel_inbox", "kernel_outbox"),
    "identity": ("identity_users", "identity_refresh_tokens"),
    "profile": ("profiles",),
    "devices": ("devices",),
    "catalog": ("catalog_playlists", "catalog_channels"),
    "live": ("live_channels", "live_epg"),
    "billing": ("billing_checkouts", "billing_subscriptions", "billing_webhook_events"),
    "playback": ("playback_events", "playback_qoe", "playback_sessions"),
    "drm": ("drm_events", "drm_licenses", "drm_policies", "drm_contents"),
    "library": ("library_favorites", "library_history", "library_progress"),
    "recommendations": ("reco_play_buckets", "reco_profile_affinity"),
    "admin": ("admin_abuse_flags", "admin_login_signals"),
}


def _rename_relations(table: str, rename: Callable[[str], str | None]) -> None:
    """PostgreSQL only: constraint, index and sequence names are schema-global,
    so the renamed legacy table's ``pk_live_epg`` / ``live_epg_id_seq`` would
    collide with the v2 table's. ``rename`` maps an old name to a new one (or
    ``None`` to keep it) — name-agnostic, so it works whether the legacy
    objects were created with or without the naming convention."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    constraints = (
        bind.execute(
            sa.text(
                "SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass)"
            ),
            {"t": table},
        )
        .scalars()
        .all()
    )
    for name in constraints:
        new = rename(name)
        if new:
            op.execute(
                f'ALTER TABLE "{table}" RENAME CONSTRAINT "{name}" TO "{new[:63]}"'
            )
    indexes = (
        bind.execute(
            sa.text("SELECT indexname FROM pg_indexes WHERE tablename = :t"),
            {"t": table},
        )
        .scalars()
        .all()
    )
    for name in indexes:  # PK / unique indexes were renamed with their constraints
        new = rename(name)
        if new:
            op.execute(f'ALTER INDEX "{name}" RENAME TO "{new[:63]}"')
    sequence = bind.execute(
        sa.text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table}
    ).scalar()
    if sequence:
        bare = sequence.split(".")[-1].strip('"')
        new = rename(bare)
        if new:
            op.execute(f'ALTER SEQUENCE {sequence} RENAME TO "{new[:63]}"')


def _to_legacy(name: str) -> str | None:
    return (
        None
        if "legacy_live_epg" in name or "live_epg" not in name
        else name.replace("live_epg", "legacy_live_epg", 1)
    )


def _from_legacy(name: str) -> str | None:
    return (
        name.replace("legacy_live_epg", "live_epg", 1)
        if "legacy_live_epg" in name
        else None
    )


def upgrade() -> None:
    op.rename_table("live_epg", "legacy_live_epg")
    _rename_relations("legacy_live_epg", _to_legacy)
    _create_kernel()
    _create_identity()
    _create_profile()
    _create_devices()
    _create_catalog()
    _create_live()
    _create_billing()
    _create_playback()
    _create_drm()
    _create_library()
    _create_recommendations()
    _create_admin()


def downgrade() -> None:
    for module in reversed(tuple(MODULE_TABLES)):
        for table in reversed(MODULE_TABLES[module]):
            op.drop_table(table)
    _rename_relations("legacy_live_epg", _from_legacy)
    op.rename_table("legacy_live_epg", "live_epg")
