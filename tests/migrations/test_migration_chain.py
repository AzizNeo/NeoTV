"""The Alembic chain: fresh install, drift, and the legacy → v2 data cut-over."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import flask_migrate
import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask

from app.kernel.db import db
from tests.support.factory import make_app

LEGACY_HEAD = "d88aab850aa0"


@pytest.fixture
def file_app(tmp_path: Path) -> Iterator[Flask]:
    app = make_app(schema="none", database_url=f"sqlite:///{tmp_path / 'm.db'}")
    with app.app_context():
        yield app
        db.session.remove()
        db.engine.dispose()


def _drift() -> list[object]:
    with db.engine.connect() as conn:
        return list(compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), db.metadata))


def test_fresh_install_reaches_head_without_drift(file_app: Flask) -> None:
    flask_migrate.upgrade()
    assert _drift() == [], "models and migrations disagree — add a revision"
    tables = set(sa.inspect(db.engine).get_table_names())
    assert "user" not in tables and "identity_users" in tables and "kernel_outbox" in tables


def _seed_legacy(conn: sa.Connection) -> None:
    ts = "2026-01-10 12:00:00.000000"  # legacy SQLite stored naive UTC text
    conn.execute(
        sa.text(
            "INSERT INTO user (id, username, password_hash, role, created_at, subscription_plan, is_active, expire_date) "
            "VALUES (1,'admin','scrypt:32768:8:1$x$y','admin',:t,'personal',1,NULL),"
            "(2,'nopass',NULL,NULL,:t,'enterprise',NULL,NULL),(3,'freebie','h','user',:t,NULL,1,NULL)"
        ),
        {"t": ts},
    )
    conn.execute(
        sa.text("INSERT INTO playlist (id,name,url,created_at) VALUES (5,'IPTV','http://p/list.m3u',:t)"), {"t": ts}
    )
    conn.execute(
        sa.text(
            'INSERT INTO channel (id,name,url,logo,"group",playlist_id) VALUES '
            "(10,'News','https://c/news.m3u8',NULL,'Haber',5),"
            "(11,'News dup','https://c/news.m3u8',NULL,'Haber',5),"  # same URL in same playlist → merged onto 10
            "(12,'Film','https://c/film.mp4',NULL,'Movies',NULL),"  # no playlist → Manual
            "(13,'Broken','rtmp://nope',NULL,NULL,NULL)"  # non-http → skipped
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO subscription (user_id, plan, status, started_at, expires_at, billing_cycle, auto_renew, created_at, updated_at) "
            "VALUES (1,'personal','active',:t,'2099-01-01 00:00:00','monthly',0,:t,:t)"
        ),
        {"t": ts},
    )
    conn.execute(
        sa.text(
            "INSERT INTO watch_progress (user_id,channel_id,last_position,total_duration,completed_ratio,is_completed,created_at,updated_at) "
            "VALUES (1,11,700,600,1.0,0,:t,:t),(1,999,5,10,0.5,0,:t,:t)"  # 11 → merged id 10; 999 → orphan
        ),
        {"t": ts},
    )
    conn.execute(sa.text("INSERT INTO favorite (user_id,channel_id,created_at) VALUES (1,10,:t),(1,11,:t)"), {"t": ts})
    conn.execute(
        sa.text(
            "INSERT INTO live_channel (id,name,stream_key,hls_url,is_live) VALUES (3,'News Live','k1','https://live.example.com/m.m3u8',1),"
            "(4,'Studio','k2',NULL,0)"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO live_epg (live_channel_id,program_name,start_time,end_time) VALUES "
            "(3,'Haber','2026-01-10 10:00:00','2026-01-10 11:00:00'),(3,'Bad','2026-01-10 12:00:00','2026-01-10 11:00:00')"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO playback_event (user_id,channel_id,event_type,position,created_at) VALUES "
            "(1,10,'play',0,:t),(1,10,'play',0,:t),(1,12,'pause',5,:t)"
        ),
        {"t": ts},
    )
    conn.execute(
        sa.text(
            "INSERT INTO device (user_id,device_id,device_name,is_active,last_seen,login_count,created_at) "
            "VALUES (1,'abc','Chrome',1,:t,3,:t)"
        ),
        {"t": ts},
    )
    conn.execute(
        sa.text("INSERT INTO drm_content (channel_id,content_id,key_id,content_key) VALUES (10,'c','k','plain')")
    )


def test_legacy_data_is_transformed_faithfully(file_app: Flask) -> None:
    flask_migrate.upgrade(revision=LEGACY_HEAD)
    with db.engine.connect() as conn:
        # Legacy databases were written with FK enforcement OFF (SQLite default) and
        # contain orphans; reproduce that so the migration is tested against reality.
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()  # end the autobegun transaction; the pragma only applies outside one
        _seed_legacy(conn)
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    flask_migrate.upgrade(revision="b2c0de000002")  # migrate step only: legacy still present for inspection
    q = lambda sql: db.session.execute(sa.text(sql)).all()  # noqa: E731

    users = {r.username: r for r in q("SELECT username, role, password_hash, is_active FROM identity_users")}
    assert users["admin"].role == "admin" and users["nopass"].password_hash.startswith("!")
    assert users["nopass"].role == "user" and users["nopass"].is_active

    assert q("SELECT COUNT(*) FROM profiles WHERE is_default")[0][0] == 3
    channels = {r.id: r for r in q("SELECT id, playlist_id, kind, group_name FROM catalog_channels")}
    manual = q("SELECT id FROM catalog_playlists WHERE is_system")[0][0]
    assert set(channels) == {10, 12}  # ids preserved, duplicate merged, non-http skipped
    assert channels[12].playlist_id == manual and channels[12].kind == "vod" and channels[10].playlist_id == 5

    subs = {r.user_id: r for r in q("SELECT user_id, plan, status, cancel_at_period_end FROM billing_subscriptions")}
    assert (subs[1].plan, subs[1].status, subs[1].cancel_at_period_end) == ("personal", "cancelled", 1)
    assert subs[2].plan == "family"  # 'enterprise' alias, plan only lived on the user row
    assert subs[3].plan == "free"

    progress = q("SELECT content_ref, position_s, duration_s, completed FROM library_progress")
    assert [(p.content_ref, p.position_s, p.completed) for p in progress] == [("catalog:10", 600, 1)]
    assert [r.content_ref for r in q("SELECT content_ref FROM library_favorites")] == ["catalog:10"]

    live = {r.id: r for r in q("SELECT id, source_type, upstream_url, ingest_key_hash FROM live_channels")}
    assert live[3].source_type == "external" and live[4].source_type == "ingest" and live[4].ingest_key_hash is None
    assert [r.title for r in q("SELECT title FROM live_epg")] == ["Haber"]

    assert q("SELECT plays FROM reco_play_buckets WHERE content_ref='catalog:10'")[0][0] == 2
    assert q("SELECT is_active FROM devices")[0][0] == 0
    assert q("SELECT COUNT(*) FROM drm_contents")[0][0] == 0  # exposed legacy keys are not carried over
    db.session.remove()

    flask_migrate.upgrade()  # contract
    assert "user" not in sa.inspect(db.engine).get_table_names()
    assert _drift() == []


def test_contract_step_refuses_to_downgrade(file_app: Flask) -> None:
    # Pin the contract step itself: from a later head PostgreSQL rolls the whole
    # downgrade back (transactional DDL) while SQLite stops part-way.
    flask_migrate.upgrade(revision="b2c0de000003")
    with pytest.raises(SystemExit):  # Flask-Migrate turns the RuntimeError into exit status 1
        flask_migrate.downgrade(revision="b2c0de000002")
    db.session.remove()
    assert db.session.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "b2c0de000003"


def test_expand_and_migrate_steps_round_trip(file_app: Flask) -> None:
    flask_migrate.upgrade(revision="b2c0de000002")
    flask_migrate.downgrade(revision=LEGACY_HEAD)
    tables = set(sa.inspect(db.engine).get_table_names())
    assert "live_epg" in tables and "identity_users" not in tables
    flask_migrate.upgrade()
    assert _drift() == []
