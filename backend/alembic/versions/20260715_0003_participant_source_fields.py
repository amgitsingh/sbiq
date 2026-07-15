"""participant source fields (phone, ideal_connection, biggest_opportunity, raw_source_data)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("phone", sa.String(50), nullable=True))
    op.add_column("participants", sa.Column("ideal_connection", sa.Text(), nullable=True))
    op.add_column("participants", sa.Column("biggest_opportunity", sa.Text(), nullable=True))
    op.add_column("participants", sa.Column("raw_source_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("participants", "raw_source_data")
    op.drop_column("participants", "biggest_opportunity")
    op.drop_column("participants", "ideal_connection")
    op.drop_column("participants", "phone")
