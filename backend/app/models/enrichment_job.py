from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.participant import Participant


class EnrichmentSource(str, enum.Enum):
    website = "website"
    tavily_web = "tavily_web"
    tavily_news = "tavily_news"
    crunchbase = "crunchbase"
    linkedin = "linkedin"
    llm_normalization = "llm_normalization"
    reused_from_cache = "reused_from_cache"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class EnrichmentJob(Base):
    __tablename__ = "enrichment_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    participant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        Enum(EnrichmentSource, values_callable=lambda e: [x.value for x in e], native_enum=False),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(JobStatus, values_callable=lambda e: [x.value for x in e], native_enum=False),
        default=JobStatus.pending,
        nullable=False,
    )
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    participant: Mapped[Participant] = relationship(
        "Participant", back_populates="enrichment_jobs"
    )
