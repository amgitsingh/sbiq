"""event context fields (agenda, matching_goals, target_sectors, event_type, expected_participant_count)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("agenda", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("matching_goals", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("target_sectors", sa.JSON(), nullable=True))
    op.add_column("events", sa.Column("event_type", sa.String(100), nullable=True))
    op.add_column("events", sa.Column("expected_participant_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "expected_participant_count")
    op.drop_column("events", "event_type")
    op.drop_column("events", "target_sectors")
    op.drop_column("events", "matching_goals")
    op.drop_column("events", "agenda")
