"""identity: one-time link purposes for e-mail change and its undo

Revision ID: b2c0de000006
Revises: b2c0de000005
Create Date: 2026-10-11

Widens the ``purpose`` check of ``identity_action_tokens``. Downgrade deletes the
links of the new purposes first (they cannot satisfy the narrower check).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c0de000006"
down_revision = "b2c0de000005"
branch_labels = None
depends_on = None

_TABLE = "identity_action_tokens"
_NAME = "ck_identity_action_tokens_purpose_valid"
_OLD = "purpose IN ('verify_email','reset_password')"
_NEW = "purpose IN ('verify_email','reset_password','change_email','revert_email')"


def _swap(condition: str) -> None:
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_constraint(op.f(_NAME), type_="check")
        batch_op.create_check_constraint(op.f(_NAME), sa.text(condition))


def upgrade() -> None:
    _swap(_NEW)


def downgrade() -> None:
    op.execute(sa.text(f"DELETE FROM {_TABLE} WHERE purpose IN ('change_email','revert_email')"))  # noqa: S608
    _swap(_OLD)
