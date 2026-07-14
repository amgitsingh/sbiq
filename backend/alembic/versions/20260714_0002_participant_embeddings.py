"""participant embeddings table with pgvector

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "participant_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("structured_profile_snapshot", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "participant_id", "event_id", name="uq_embedding_participant_event"
        ),
    )
    op.create_index("ix_participant_embeddings_id", "participant_embeddings", ["id"])
    op.create_index(
        "ix_participant_embeddings_participant_id",
        "participant_embeddings",
        ["participant_id"],
    )
    op.create_index(
        "ix_participant_embeddings_event_id",
        "participant_embeddings",
        ["event_id"],
    )

    # Set real vector type (requires pgvector extension, enabled in migration 0001)
    op.execute(
        "ALTER TABLE participant_embeddings "
        "ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::vector(1536)"
    )

    # HNSW index for fast approximate nearest-neighbour cosine search
    op.execute(
        "CREATE INDEX ix_participant_embeddings_hnsw "
        "ON participant_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_participant_embeddings_hnsw")
    op.drop_table("participant_embeddings")
