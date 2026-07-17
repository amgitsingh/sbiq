from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.participant_embedding import ParticipantEmbedding

DEFAULT_TOP_N = 20


def find_similar_participants(
    db: Session,
    *,
    participant_id: int,
    event_id: int,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict]:
    """Cosine similarity search for a participant's closest candidates within
    their own event. Always filtered by event_id - per the confirmed
    architecture decision, vector search never crosses events even though the
    same participant may have embeddings for other events too.

    Returns [] if this participant has no embedding yet (not embedded, or
    embedding generation failed and hasn't been retried). Excludes the
    participant themselves from the results. Ordered by pgvector's cosine
    distance ascending (nearest first), which lets Postgres use the HNSW
    index instead of computing and sorting the full similarity in Python.
    """
    target = (
        db.query(ParticipantEmbedding)
        .filter(
            ParticipantEmbedding.participant_id == participant_id,
            ParticipantEmbedding.event_id == event_id,
        )
        .first()
    )
    if target is None:
        return []

    distance = ParticipantEmbedding.embedding.cosine_distance(target.embedding)
    rows = (
        db.query(ParticipantEmbedding.participant_id, distance.label("distance"))
        .filter(
            ParticipantEmbedding.event_id == event_id,
            ParticipantEmbedding.participant_id != participant_id,
        )
        .order_by(distance)
        .limit(top_n)
        .all()
    )

    return [
        {"participant_id": row.participant_id, "similarity_score": 1 - row.distance}
        for row in rows
    ]
