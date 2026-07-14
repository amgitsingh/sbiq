from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
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
    status: Mapped[str] = mapped_column(
        Enum(EventStatus, values_callable=lambda e: [x.value for x in e]),
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
