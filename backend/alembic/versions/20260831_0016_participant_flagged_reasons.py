"""add participants.flagged_reasons

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-31

Real client request: too many participants (44% on one real event) were
permanently stuck un-matchable just for leaving the intent fields blank on
the signup form, even when enrichment later found real company/professional
signal about them. This column lets enrichment_tasks.py's eligibility-unlock
check tell "review because the form was blank" apart from "review because
of tier ambiguity/duplicate submission" - only the former is safe to
auto-resolve.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("flagged_reasons", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("participants", "flagged_reasons")
