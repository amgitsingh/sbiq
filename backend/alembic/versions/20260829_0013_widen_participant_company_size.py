"""widen participants.company_size from varchar(50) to varchar(255)

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-29

Real bug found uploading a real participant export: company_size is
free-text (never validated as numeric - see sector_size.company_size_score,
which parses a number out of whatever string is stored), but a legitimate
long-form answer ("Organization is in liaison with several secondary
schools and the Vrije Universiteit") exceeded the 50-char column and raised
StringDataRightTruncation - which failed the ENTIRE batch insert for that
upload, not just the one offending row. Widened to 255 to match this
table's other free-text columns (sector/company/designation).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "participants", "company_size", type_=sa.String(length=255), existing_type=sa.String(length=50)
    )


def downgrade() -> None:
    op.alter_column(
        "participants", "company_size", type_=sa.String(length=50), existing_type=sa.String(length=255)
    )
