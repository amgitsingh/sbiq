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


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgresql():
        # Vector column — 1536 dims for text-embedding-3-small
        embedding_col = sa.Column(
            "embedding",
            sa.Text(),  # placeholder type; overridden by raw DDL below
            nullable=False,
        )
    else:
        # SQLite local dev — store as JSON; vector search won't work but schema loads
        embedding_col = sa.Column("embedding", sa.JSON(), nullable=True)

    op.create_table(
        "participant_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        embedding_col,
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

    if _is_postgresql():
        # Alter the column to the real vector type after table creation
        op.execute("ALTER TABLE participant_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")

        # HNSW index for fast approximate nearest-neighbour cosine search
        op.execute(
            "CREATE INDEX ix_participant_embeddings_hnsw "
            "ON participant_embeddings "
            "USING hnsw (embedding vector_cosine_ops)"
        )

        # Plain B-tree index on event_id for the WHERE event_id = ? filter
        # (already created above as a standard index — no extra DDL needed)


def downgrade() -> None:
    if _is_postgresql():
        op.execute("DROP INDEX IF EXISTS ix_participant_embeddings_hnsw")

    op.drop_table("participant_embeddings")
