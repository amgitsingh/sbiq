from app.workers.celery_app import celery_app


@celery_app.task(
    name="app.workers.enrichment_tasks.enrich_participant",
    bind=True,
    queue="enrichment",
    max_retries=3,
    default_retry_delay=60,
)
def enrich_participant(self, participant_id: int) -> dict:
    """Run the full 5-source enrichment pipeline for a single participant."""
    # Implemented in Task 20 (Phase 3 — Enrichment Pipeline)
    raise NotImplementedError


@celery_app.task(
    name="app.workers.enrichment_tasks.batch_enrich_event",
    bind=True,
    queue="enrichment",
)
def batch_enrich_event(self, event_id: int) -> dict:
    """Fan out enrich_participant tasks for all participants in an event."""
    # Implemented in Task 20 (Phase 3 — Enrichment Pipeline)
    raise NotImplementedError
