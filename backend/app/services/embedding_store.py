from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.participant_embedding import ParticipantEmbedding

logger = logging.getLogger(__name__)


def upsert_participant_embedding(
    db: Session,
    *,
    participant_id: int,
    event_id: int,
    embedding: list[float],
    structured_profile: dict,
) -> None:
    """Insert or refresh a participant's embedding for this event.

    Upsert key is (participant_id, event_id), not participant_id alone - the
    same participant re-enriched for a different event gets its own embedding
    row, since looking_for/offerings (and therefore the embedded text) are
    per-event verbatim answers, not stable person facts.
    """
    row = (
        db.query(ParticipantEmbedding)
        .filter(
            ParticipantEmbedding.participant_id == participant_id,
            ParticipantEmbedding.event_id == event_id,
        )
        .first()
    )
    if row is None:
        db.add(
            ParticipantEmbedding(
                participant_id=participant_id,
                event_id=event_id,
                embedding=embedding,
                structured_profile_snapshot=structured_profile,
            )
        )
    else:
        row.embedding = embedding
        row.structured_profile_snapshot = structured_profile
    db.commit()
