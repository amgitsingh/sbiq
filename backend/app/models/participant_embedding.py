from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.participant import Participant


class ParticipantEmbedding(Base):
    __tablename__ = "participant_embeddings"
    __table_args__ = (
        # Upsert key — one embedding row per participant per event
        UniqueConstraint("participant_id", "event_id", name="uq_embedding_participant_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    participant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized for fast event-scoped WHERE filtering without a JOIN
    event_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # 1536 dimensions — OpenAI text-embedding-3-small
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=False)

    # Snapshot of the structured profile used to generate this embedding
    structured_profile_snapshot: Mapped[dict | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    participant: Mapped[Participant] = relationship(
        "Participant", backref="embedding"
    )
