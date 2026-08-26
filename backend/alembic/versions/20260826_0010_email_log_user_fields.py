"""fix email_log: replace triggered_by_user_id with sender_user_id/receiver_user_id (docs/PLAN.md Phase 8, Task 57)

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-26

Migration 0009 gave email_log only participant-pair FKs, on the assumption
it was exclusively for QBCals' own match emails. Porting IndMatchmaking's
registrations domain (Task 57) revealed email_log is also used for
admin<->user emails (registration confirmations, activation credentials),
which need real user_master FKs instead. email_log has zero rows at this
point (created in 0009, never yet used by any code) - safe to alter freely.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("email_log", "triggered_by_user_id", new_column_name="sender_user_id")
    op.add_column(
        "email_log",
        sa.Column(
            "receiver_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_master.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("email_log", "receiver_user_id")
    op.alter_column("email_log", "sender_user_id", new_column_name="triggered_by_user_id")
