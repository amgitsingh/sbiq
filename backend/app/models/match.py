from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.participant import Participant


class MatchStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_a_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )
    participant_b_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("participants.id", ondelete="CASCADE"), nullable=False
    )

    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)

    # LLM output — array of reasoning bullet strings
    reasoning: Mapped[list | None] = mapped_column(JSON)
    email_draft: Mapped[str | None] = mapped_column(Text)
    linkedin_draft: Mapped[str | None] = mapped_column(Text)

    # On-demand translation cache, keyed by language code:
    # {"nl": {"reasoning": [...], "email_draft": "...", "linkedin_draft": "..."}}.
    # Reset to None whenever store_match overwrites this row's reasoning/
    # drafts (a re-run), so a stale translation of the old content is never
    # served after a rematch.
    translations: Mapped[dict | None] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(
        Enum(MatchStatus, values_callable=lambda e: [x.value for x in e], native_enum=False),
        default=MatchStatus.pending,
        nullable=False,
    )
    # True when this record was auto-created as the reverse of another match
    is_bidirectional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    event: Mapped[Event] = relationship("Event", back_populates="matches")
    participant_a: Mapped[Participant] = relationship(
        "Participant", foreign_keys=[participant_a_id], back_populates="matches_as_a"
    )
    participant_b: Mapped[Participant] = relationship(
        "Participant", foreign_keys=[participant_b_id], back_populates="matches_as_b"
    )
