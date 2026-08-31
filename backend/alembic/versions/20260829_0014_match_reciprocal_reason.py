"""add matches.reciprocal_reason

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-29

Supports the new combined per-participant matches email
(docs/mail-template.docx), whose "Why you could be interesting to [them]"
section needs content distinct from the existing `reasoning` column
(which is about the candidate's value to the participant, not the reverse).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("reciprocal_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "reciprocal_reason")
