from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.participant import Participant


class EventStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    completed = "completed"


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    date: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    matching_rules: Mapped[dict | None] = mapped_column(JSON)

    # Purpose/description of the event - what happens, why it's being run.
    agenda: Mapped[str | None] = mapped_column(Text)
    # Explicit "who should meet whom" intent (e.g. "connect early-stage
    # founders with Series A investors") - distinct from agenda, written
    # specifically as guidance for the matching LLM, not just event
    # description. See llm_matcher.build_event_context, which reads this.
    matching_goals: Mapped[str | None] = mapped_column(Text)
    # Sectors the event is centered on. Free text/JSON list, not enforced -
    # deliberately kept open in case a real event doesn't fit the known list.
    # Suggested vocabulary: reuse app.services.matching.sector_size's
    # SECTOR_KEYWORDS categories (finance_banking, real_estate,
    # health_wellness, hospitality_tourism, culture_entertainment,
    # media_photography, education_training, administrative_hr, technology,
    # retail_ecommerce, manufacturing, consulting, legal, logistics,
    # construction, agriculture_food, energy, nonprofit_government,
    # telecommunications) - same taxonomy classify_sector() uses on
    # participants, so values here stay comparable to what participants
    # actually get classified as.
    target_sectors: Mapped[list | None] = mapped_column(JSON)
    # Free-text category - not an enum, since no code branches on it yet and
    # this list is a starting suggestion, not derived from existing code.
    # Suggested vocabulary: networking, pitch_day, conference, trade_show,
    # workshop, mixer, panel.
    event_type: Mapped[str | None] = mapped_column(String(100))
    # Pre-upload headcount estimate, for admin display only - not wired into
    # cost_estimator.py (that reads real uploaded participant rows instead).
    expected_participant_count: Mapped[int | None] = mapped_column(Integer)
    # "en" / "nl" - language for LLM-generated content (company.summary,
    # match reasoning, reciprocal_reason, linkedin_draft). None is treated
    # as "en" everywhere it's read (llm_normalizer.py, llm_matcher.py,
    # events.py::send_match_email) - no behavior change for existing events.
    # Deliberately per-event, not per-participant: a shared reasoning/email
    # artifact between two participants can't have two languages at once.
    # looking_for/offerings are exempt - already guaranteed verbatim/
    # never-translated regardless of this setting.
    content_language: Mapped[str | None] = mapped_column(String(10))
    # Ported/added for docs/PLAN.md Phase 8 (merge with IndMatchmaking).
    # location: carried over from IndMatchmaking's EventMaster (QBCals' own
    # Event never had a venue/location field). owner_user_id: new - QBCals
    # had no ownership concept at all before this merge; nullable/SET NULL
    # since existing events predate this column and an owner account being
    # deleted shouldn't cascade-delete real event/participant data. See
    # Task 59 for how this is actually enforced (this column alone doesn't
    # restrict anything by itself).
    location: Mapped[str | None] = mapped_column(String(255))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_master.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        Enum(EventStatus, values_callable=lambda e: [x.value for x in e], native_enum=False),
        default=EventStatus.draft,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    participants: Mapped[list[Participant]] = relationship(
        "Participant", back_populates="event", cascade="all, delete-orphan"
    )
    matches: Mapped[list[Match]] = relationship(
        "Match", back_populates="event", cascade="all, delete-orphan"
    )
