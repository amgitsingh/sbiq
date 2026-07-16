from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enriched_profile import EnrichedProfile

logger = logging.getLogger(__name__)


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def get_reusable_profile(db: Session, email: str | None) -> EnrichedProfile | None:
    """Return the cached EnrichedProfile row for this email if one exists and
    is still fresh (within settings.ENRICHMENT_REUSE_MAX_AGE_DAYS). Returns
    None if there's no cached profile, it's stale, or email is blank - all of
    which mean "go enrich fresh". Returns the row (not just the profile dict)
    so callers can log last_enriched_at/age for traceability.
    """
    normalized = normalize_email(email)
    if not normalized:
        return None

    row = db.query(EnrichedProfile).filter(EnrichedProfile.email == normalized).first()
    if row is None:
        return None

    max_age = timedelta(days=settings.ENRICHMENT_REUSE_MAX_AGE_DAYS)
    age = datetime.utcnow() - row.last_enriched_at
    if age > max_age:
        logger.info(f"Cached profile for {normalized!r} is stale ({age.days}d old) - will re-enrich")
        return None

    logger.info(f"Reusing cached profile for {normalized!r} ({age.days}d old)")
    return row


def upsert_enriched_profile(db: Session, email: str | None, structured_profile: dict) -> None:
    """Insert or refresh the cached profile for this email. Only call this
    after a genuinely successful fresh enrichment - never after a reuse.
    """
    normalized = normalize_email(email)
    if not normalized:
        return

    now = datetime.utcnow()
    row = db.query(EnrichedProfile).filter(EnrichedProfile.email == normalized).first()
    if row is None:
        db.add(EnrichedProfile(email=normalized, structured_profile=structured_profile, last_enriched_at=now))
    else:
        row.structured_profile = structured_profile
        row.last_enriched_at = now
    db.commit()
