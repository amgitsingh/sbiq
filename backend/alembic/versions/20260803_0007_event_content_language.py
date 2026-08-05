"""event content_language (en/nl - language for LLM-generated content)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("content_language", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "content_language")
