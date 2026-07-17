import logging

from app.core.database import session_scope
from app.models.participant import EnrichmentStatus, Participant
from app.services.embedding import EmbeddingGenerationError, generate_embedding
from app.services.embedding_store import upsert_participant_embedding
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.embedding_tasks.embed_participant",
    bind=True,
    queue="enrichment",
)
def embed_participant(self, participant_id: int) -> dict:
    """(Re-)embed a single already-enriched participant.

    Unlike enrich_participant's automatic embedding call (Task 23), this task
    never runs the enrichment pipeline - it only (re)embeds whatever
    structured_profile already exists. It's the manual recovery/backfill path:
    a participant enriched before this feature existed, or one whose automatic
    embedding attempt failed and was swallowed (see enrichment_tasks.py).
    """
    with session_scope() as db:
        participant = db.get(Participant, participant_id)
        if participant is None:
            raise ValueError(f"Participant {participant_id} not found")

        if participant.enrichment_status != EnrichmentStatus.done or not participant.structured_profile:
            return {"participant_id": participant_id, "status": "skipped", "reason": "not enriched"}

        try:
            vector, tokens = generate_embedding(participant.structured_profile)
        except EmbeddingGenerationError as e:
            logger.warning(f"Embedding generation failed for participant {participant_id}: {e}")
            return {"participant_id": participant_id, "status": "failed", "error": str(e)}

        upsert_participant_embedding(
            db,
            participant_id=participant.id,
            event_id=participant.event_id,
            embedding=vector,
            structured_profile=participant.structured_profile,
        )
        return {"participant_id": participant_id, "status": "done", "tokens": tokens}


@celery_app.task(
    name="app.workers.embedding_tasks.batch_embed_event",
    bind=True,
    queue="enrichment",
)
def batch_embed_event(self, event_id: int) -> dict:
    """Fan out embed_participant tasks for all enriched participants in an event.

    Skips participants whose enrichment_status isn't done - matches Task 25's
    spec exactly (embedding requires a structured profile to embed).
    """
    with session_scope() as db:
        participant_ids = [
            pid
            for (pid,) in db.query(Participant.id)
            .filter(
                Participant.event_id == event_id,
                Participant.enrichment_status == EnrichmentStatus.done,
            )
            .all()
        ]

    for pid in participant_ids:
        embed_participant.delay(pid)

    return {"event_id": event_id, "dispatched": len(participant_ids)}
