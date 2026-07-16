from sqlalchemy.orm import Session

from app.core.database import session_scope
from app.models.enrichment_job import EnrichmentJob, EnrichmentSource, JobStatus
from app.models.participant import EnrichmentStatus, Participant
from app.services.enrichment.company_enrichment import get_company_enrichment
from app.services.enrichment.linkedin_scraper import scrape_linkedin_profile
from app.services.enrichment.llm_normalizer import (
    ProfileNormalizationError,
    normalize_participant_profile,
)
from app.services.enrichment.merger import build_enrichment_context
from app.workers.celery_app import celery_app


def _record_job(
    db: Session,
    participant_id: int,
    source: EnrichmentSource,
    raw_data,
    *,
    status: JobStatus = JobStatus.done,
    error: str | None = None,
) -> None:
    db.add(
        EnrichmentJob(
            participant_id=participant_id,
            source=source,
            status=status,
            raw_data=raw_data,
            error_message=error,
        )
    )
    db.commit()


@celery_app.task(
    name="app.workers.enrichment_tasks.enrich_participant",
    bind=True,
    queue="enrichment",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(ProfileNormalizationError,),
)
def enrich_participant(self, participant_id: int) -> dict:
    """Run the full 5-source enrichment pipeline for a single participant."""
    with session_scope() as db:
        participant = db.get(Participant, participant_id)
        if participant is None:
            raise ValueError(f"Participant {participant_id} not found")

        participant.enrichment_status = EnrichmentStatus.enriching
        db.commit()

        company_data = get_company_enrichment(
            company_name=participant.company,
            event_id=participant.event_id,
            website_url=participant.website,
        )
        _record_job(db, participant.id, EnrichmentSource.website, company_data.get("website"))
        _record_job(db, participant.id, EnrichmentSource.tavily_web, company_data.get("tavily_web"))
        _record_job(db, participant.id, EnrichmentSource.tavily_news, company_data.get("tavily_news"))
        _record_job(db, participant.id, EnrichmentSource.crunchbase, company_data.get("crunchbase"))

        linkedin_profile = scrape_linkedin_profile(participant.linkedin_url or "")
        _record_job(db, participant.id, EnrichmentSource.linkedin, linkedin_profile)

        merged_context = build_enrichment_context(
            name=participant.name,
            company=participant.company,
            designation=participant.designation,
            looking_for=participant.looking_for,
            offerings=participant.offerings,
            ideal_connection=participant.ideal_connection,
            biggest_opportunity=participant.biggest_opportunity,
            company_enrichment=company_data,
            linkedin_profile=linkedin_profile,
        )

        try:
            profile = normalize_participant_profile(
                merged_context,
                looking_for=participant.looking_for,
                offerings=participant.offerings,
            )
        except ProfileNormalizationError as e:
            _record_job(
                db,
                participant.id,
                EnrichmentSource.llm_normalization,
                None,
                status=JobStatus.failed,
                error=str(e),
            )
            participant.enrichment_status = EnrichmentStatus.failed
            db.commit()
            raise

        _record_job(db, participant.id, EnrichmentSource.llm_normalization, profile)
        participant.structured_profile = profile
        participant.enrichment_status = EnrichmentStatus.done
        db.commit()

        return {"participant_id": participant_id, "status": "done"}


@celery_app.task(
    name="app.workers.enrichment_tasks.batch_enrich_event",
    bind=True,
    queue="enrichment",
)
def batch_enrich_event(self, event_id: int) -> dict:
    """Fan out enrich_participant tasks for all participants in an event."""
    with session_scope() as db:
        participant_ids = [
            pid for (pid,) in db.query(Participant.id).filter(Participant.event_id == event_id).all()
        ]

    for pid in participant_ids:
        enrich_participant.delay(pid)

    return {"event_id": event_id, "dispatched": len(participant_ids)}
