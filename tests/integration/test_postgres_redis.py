"""End-to-end scenarios re-run on PostgreSQL + Redis (see conftest)."""

from __future__ import annotations

import pytest
from flask import Flask

from app.kernel.db import db
from app.kernel.outbox.repository import InboxRepository

# Re-collect the backend-agnostic suites against the real engines.
from tests.e2e.test_account_recovery import *  # noqa: F403
from tests.e2e.test_billing import *  # noqa: F403
from tests.e2e.test_drm_library_reco_admin import *  # noqa: F403
from tests.e2e.test_identity_profiles import *  # noqa: F403
from tests.e2e.test_playback_catalog_live import *  # noqa: F403
from tests.migrations.test_migration_chain import (  # noqa: F401
    test_contract_step_refuses_to_downgrade,
    test_expand_and_migrate_steps_round_trip,
    test_fresh_install_reaches_head_without_drift,
)

pytestmark = pytest.mark.integration


def test_inbox_claim_reports_insertion_on_psycopg(app: Flask) -> None:
    """Regression: psycopg 3 reports rowcount=-1 for INSERT; claims must use RETURNING."""
    with app.app_context():
        inbox = InboxRepository(db.session)
        assert inbox.try_claim("evt-1", "test.consumer") is True
        assert inbox.try_claim("evt-1", "test.consumer") is False
        db.session.rollback()
