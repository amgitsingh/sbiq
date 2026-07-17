"""participant matching_status (pending/matching/done/failed, mirrors enrichment_status)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "participants",
        sa.Column("matching_status", sa.String(50), nullable=False, server_default="pending"),
    )


def downgrade() -> None:
    op.drop_column("participants", "matching_status")
