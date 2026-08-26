"""fix tz-naive columns explicitly written with datetime.now(UTC) (docs/PLAN.md Phase 8, Task 57)

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-26

The ported async auth/registrations code (Task 57) follows IndMatchmaking's
own convention of writing explicit datetime.now(UTC) (timezone-aware) values
into user_master.approved_at, email_log.sent_at, and matches.reviewed_at.
asyncpg rejects inserting a tz-aware Python datetime into a naive
TIMESTAMP WITHOUT TIME ZONE column outright. All three columns are
nullable and currently NULL on every real row (matches.reviewed_at
specifically - task 64 hasn't run yet), so this ALTER is non-destructive.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("user_master", "approved_at", type_=sa.DateTime(timezone=True))
    op.alter_column("email_log", "sent_at", type_=sa.DateTime(timezone=True))
    op.alter_column("matches", "reviewed_at", type_=sa.DateTime(timezone=True))


def downgrade() -> None:
    op.alter_column("matches", "reviewed_at", type_=sa.DateTime(timezone=False))
    op.alter_column("email_log", "sent_at", type_=sa.DateTime(timezone=False))
    op.alter_column("user_master", "approved_at", type_=sa.DateTime(timezone=False))
