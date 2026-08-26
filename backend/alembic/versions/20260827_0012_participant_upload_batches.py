"""add participant_upload_batches (IndMatchmaking-parity: persisted upload audit trail)

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-27

QBCals-native, not a port of IndMatchmaking's ExcelUpload/ExcelRawData
shadow tables (deliberately eliminated earlier in Phase 8) - restores the
"queryable after the fact" capability those tables provided (which rows
were rejected on a given upload, and why) as one row per upload call
instead of one row per source Excel row.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "participant_upload_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_master.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("parse_skipped", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False),
        sa.Column("flagged_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("unmapped_headers", sa.JSON(), nullable=True),
        sa.Column("rejected_details", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_participant_upload_batches_event_id", "participant_upload_batches", ["event_id"]
    )
    op.create_index(
        "ix_participant_upload_batches_status", "participant_upload_batches", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_participant_upload_batches_status", table_name="participant_upload_batches")
    op.drop_index("ix_participant_upload_batches_event_id", table_name="participant_upload_batches")
    op.drop_table("participant_upload_batches")
