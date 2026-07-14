"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # pgvector extension — PostgreSQL only
    if _is_postgresql():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("date", sa.String(50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("matching_rules", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_id", "events", ["id"])

    op.create_table(
        "participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("designation", sa.String(255), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("sector", sa.String(255), nullable=True),
        sa.Column("company_size", sa.String(50), nullable=True),
        sa.Column("membership_tier", sa.String(50), nullable=False, server_default="normal_member"),
        sa.Column("looking_for", sa.Text(), nullable=True),
        sa.Column("offerings", sa.Text(), nullable=True),
        sa.Column("enrichment_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("participant_status", sa.String(50), nullable=False, server_default="eligible"),
        sa.Column("structured_profile", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_participants_id", "participants", ["id"])
    op.create_index("ix_participants_event_id", "participants", ["event_id"])
    op.create_index("ix_participants_email", "participants", ["email"])

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("participant_a_id", sa.Integer(), nullable=False),
        sa.Column("participant_b_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.JSON(), nullable=True),
        sa.Column("email_draft", sa.Text(), nullable=True),
        sa.Column("linkedin_draft", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("is_bidirectional", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_a_id"], ["participants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_b_id"], ["participants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_matches_id", "matches", ["id"])
    op.create_index("ix_matches_event_id", "matches", ["event_id"])

    op.create_table(
        "enrichment_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_enrichment_jobs_id", "enrichment_jobs", ["id"])
    op.create_index("ix_enrichment_jobs_participant_id", "enrichment_jobs", ["participant_id"])


def downgrade() -> None:
    op.drop_table("enrichment_jobs")
    op.drop_table("matches")
    op.drop_table("participants")
    op.drop_table("events")

    if _is_postgresql():
        op.execute("DROP EXTENSION IF EXISTS vector")
