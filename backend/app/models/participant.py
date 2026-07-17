from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.enrichment_job import EnrichmentJob
    from app.models.event import Event
    from app.models.match import Match


class MembershipTier(str, enum.Enum):
    sponsor = "sponsor"
    premium_member = "premium_member"
    business_member = "business_member"
    normal_member = "normal_member"
    non_member = "non_member"


class EnrichmentStatus(str, enum.Enum):
    pending = "pending"
    enriching = "enriching"
    done = "done"
    failed = "failed"


class ParticipantStatus(str, enum.Enum):
    eligible = "eligible"
    limited = "limited"
    review = "review"


class MatchingStatus(str, enum.Enum):
    pending = "pending"
    matching = "matching"
    done = "done"
    failed = "failed"


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Core identity (from Excel)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    company: Mapped[str | None] = mapped_column(String(255))
    designation: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(500))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))

    # Segmentation
    sector: Mapped[str | None] = mapped_column(String(255))
    company_size: Mapped[str | None] = mapped_column(String(50))
    membership_tier: Mapped[str] = mapped_column(
        Enum(MembershipTier, values_callable=lambda e: [x.value for x in e], native_enum=False),
        default=MembershipTier.normal_member,
        nullable=False,
    )

    # Matchmaking intent — verbatim from Excel, never modified by LLM
    looking_for: Mapped[str | None] = mapped_column(Text)
    offerings: Mapped[str | None] = mapped_column(Text)

    # Supplementary matchmaking signal — distinct from looking_for/offerings above,
    # not verbatim-protected, not modified by LLM normalization either.
    ideal_connection: Mapped[str | None] = mapped_column(Text)
    biggest_opportunity: Mapped[str | None] = mapped_column(Text)

    # Pipeline state
    enrichment_status: Mapped[str] = mapped_column(
        Enum(EnrichmentStatus, values_callable=lambda e: [x.value for x in e], native_enum=False),
        default=EnrichmentStatus.pending,
        nullable=False,
    )
    participant_status: Mapped[str] = mapped_column(
        Enum(ParticipantStatus, values_callable=lambda e: [x.value for x in e], native_enum=False),
        default=ParticipantStatus.eligible,
        nullable=False,
    )
    matching_status: Mapped[str] = mapped_column(
        Enum(MatchingStatus, values_callable=lambda e: [x.value for x in e], native_enum=False),
        default=MatchingStatus.pending,
        nullable=False,
    )

    # Normalized output from LLM enrichment step
    structured_profile: Mapped[dict | None] = mapped_column(JSON)

    # Full original upload row (original header text -> raw cell value), so any
    # organizer-specific question with no dedicated column is never lost.
    raw_source_data: Mapped[dict | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    event: Mapped[Event] = relationship("Event", back_populates="participants")
    enrichment_jobs: Mapped[list[EnrichmentJob]] = relationship(
        "EnrichmentJob", back_populates="participant", cascade="all, delete-orphan"
    )
    matches_as_a: Mapped[list[Match]] = relationship(
        "Match", foreign_keys="Match.participant_a_id", back_populates="participant_a"
    )
    matches_as_b: Mapped[list[Match]] = relationship(
        "Match", foreign_keys="Match.participant_b_id", back_populates="participant_b"
    )
