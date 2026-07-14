from app.workers.celery_app import celery_app


@celery_app.task(
    name="app.workers.matching_tasks.match_participant",
    bind=True,
    queue="matching",
    max_retries=2,
    default_retry_delay=30,
)
def match_participant(self, participant_id: int, event_id: int) -> dict:
    """Run similarity search → rule engine → LLM reasoning for one participant."""
    # Implemented in Task 32 (Phase 5 — Matching Engine)
    raise NotImplementedError


@celery_app.task(
    name="app.workers.matching_tasks.batch_match_event",
    bind=True,
    queue="matching",
)
def batch_match_event(self, event_id: int) -> dict:
    """Fan out match_participant tasks for all embedded participants in an event."""
    # Implemented in Task 32 (Phase 5 — Matching Engine)
    raise NotImplementedError
