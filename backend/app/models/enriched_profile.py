from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base


class EnrichedProfile(Base):
    """A durable, cross-event "known person" record keyed by email.

    Separate from Participant (event-scoped registration data) and separate
    from the Task 17 Redis cache (short-lived, company-level, within-batch
    dedup only). last_enriched_at is set explicitly only on a genuine fresh
    enrichment success, never via onupdate, so it can't drift for unrelated
    reasons.
    """

    __tablename__ = "enriched_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    structured_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    last_enriched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
