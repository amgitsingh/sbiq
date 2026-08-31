"""drop matches.email_draft

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-31

The LLM no longer generates a free-form email_draft (real user request:
"the email draft should contain the actual email that will be sent" - the
LLM-authored version was neither used by either send path (per-pair or
combined) nor accurate to the actual sent content). The real/preview email
is now composed deterministically from reasoning/reciprocal_reason/
linkedin_draft at send/read time - see
app/services/matching/participant_email_composer.py - never stored.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("matches", "email_draft")


def downgrade() -> None:
    op.add_column("matches", sa.Column("email_draft", sa.Text(), nullable=True))
