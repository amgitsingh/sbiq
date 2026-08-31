import copy
import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import session_scope
from app.models.enrichment_job import EnrichmentJob, EnrichmentSource, JobStatus
from app.models.event import Event
from app.models.participant import EnrichmentStatus, Participant, ParticipantStatus
from app.services.enrichment.company_enrichment import get_company_enrichment
from app.services.enrichment.linkedin_scraper import scrape_linkedin_profile
from app.services.enrichment.llm_normalizer import (
    ProfileNormalizationError,
    normalize_participant_profile,
)
from app.services.embedding import EmbeddingGenerationError, generate_embedding
from app.services.embedding_store import upsert_participant_embedding
from app.services.enrichment.merger import build_enrichment_context
from app.services.enrichment.profile_reuse import (
    get_reusable_profile,
    normalize_email,
    upsert_enriched_profile,
)
from app.services.enrichment.tavily_web_search import search_person
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# One extra normalization attempt, on top of llm_normalizer's own internal
# retry-once, after a short delay to let a transient issue (e.g. a rate
# limit) clear - reusing the already-computed merged_context, never
# re-running the 5 sources. Previously this was a Celery-level
# autoretry_for(ProfileNormalizationError) on the whole task, which redid all
# 5 sources (and wrote 5 redundant EnrichmentJob rows) just to retry the one
# step that actually failed.
EXTRA_NORMALIZATION_RETRY_DELAY_SECONDS = 15


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


def _normalize_with_one_extra_retry(
    merged_context: str,
    *,
    looking_for: str | None,
    offerings: str | None,
    source_urls: list[str] | None = None,
    content_language: str | None = None,
) -> dict:
    """Call normalize_participant_profile, and if it still fails (both of its
    own internal attempts exhausted), wait briefly and try once more before
    giving up. Never re-runs the 5 sources - merged_context is already built.
    """
    try:
        return normalize_participant_profile(
            merged_context,
            looking_for=looking_for,
            offerings=offerings,
            source_urls=source_urls,
            content_language=content_language,
        )
    except ProfileNormalizationError as first_error:
        logger.warning(
            f"Normalization failed, retrying once more after "
            f"{EXTRA_NORMALIZATION_RETRY_DELAY_SECONDS}s: {first_error}"
        )
        time.sleep(EXTRA_NORMALIZATION_RETRY_DELAY_SECONDS)
        return normalize_participant_profile(
            merged_context,
            looking_for=looking_for,
            offerings=offerings,
            source_urls=source_urls,
            content_language=content_language,
        )


# The one flagged_reasons value that's safe to auto-resolve once enrichment
# finds real signal - must match validation.py's exact string. Deliberately
# NOT auto-resolving tier-ambiguity or duplicate-submission flags (those
# genuinely need a human: tier affects billing/priority, a duplicate
# submission needs someone to confirm which answer is authoritative) - only
# unlocked when this is the row's SOLE flagged reason (see
# _maybe_unlock_review_status).
_BLANK_INTENT_FLAG_REASON = "no looking_for or offerings - needs manual review"


def _has_usable_enrichment_signal(profile: dict) -> bool:
    """True if enrichment found any real company-level content to go on,
    even though the participant's own looking_for/offerings stayed blank
    (those two fields are never LLM-inferred - see llm_normalizer.py's
    verbatim guarantee, so they're never a source of signal here).
    """
    company = (profile or {}).get("company") or {}
    return bool(
        company.get("summary")
        or company.get("industry")
        or company.get("products")
        or company.get("services")
    )


def _maybe_unlock_review_status(participant: Participant, profile: dict) -> None:
    """Real client request: participants who left both looking_for and
    offerings blank on the signup form were permanently stuck un-matchable
    (participant_status stayed "review" forever, set once at ingestion -
    see match_participant's eligibility check), even when enrichment later
    found a real company profile for them. Flips status back to "eligible"
    once enrichment actually finds something to go on - narrowly scoped to
    ONLY the blank-intent-fields case (flagged_reasons must be exactly that
    one reason - a row also flagged for tier ambiguity or a duplicate
    submission is left alone; those need a human, not enrichment).

    Idempotent/no-op if the participant isn't currently "review", or the
    flag was for a different/additional reason, or enrichment found nothing
    usable - safe to call unconditionally after every enrichment run
    (including cache-reuse hits).
    """
    if participant.participant_status != ParticipantStatus.review:
        return
    if participant.flagged_reasons != [_BLANK_INTENT_FLAG_REASON]:
        return
    if not _has_usable_enrichment_signal(profile):
        return
    participant.participant_status = ParticipantStatus.eligible
    logger.info(f"Participant {participant.id} unlocked for matching - enrichment found usable signal")


def _embed_and_store(db: Session, participant: Participant, profile: dict) -> None:
    """Generate and upsert this participant's embedding for their event.

    Best-effort: embedding failure does not fail enrichment - the structured
    profile is already valid and stored, which is what enrichment_status
    tracks. A missing embedding is recoverable later via Task 25's dedicated
    /embed endpoint, so it's logged and swallowed here rather than raised.
    """
    try:
        vector, _tokens = generate_embedding(profile)
        upsert_participant_embedding(
            db,
            participant_id=participant.id,
            event_id=participant.event_id,
            embedding=vector,
            structured_profile=profile,
        )
    except EmbeddingGenerationError as e:
        logger.warning(f"Embedding generation failed for participant {participant.id}: {e}")


@celery_app.task(
    name="app.workers.enrichment_tasks.enrich_participant",
    bind=True,
    queue="enrichment",
)
def enrich_participant(self, participant_id: int) -> dict:
    """Run the full 5-source enrichment pipeline for a single participant."""
    with session_scope() as db:
        participant = db.get(Participant, participant_id)
        if participant is None:
            raise ValueError(f"Participant {participant_id} not found")

        event = db.get(Event, participant.event_id)
        content_language = event.content_language if event else None

        if settings.ENABLE_ENRICHMENT_REUSE:
            cached = get_reusable_profile(db, participant.email)
            if cached is not None:
                # NOTE: a cache hit reuses company.summary as originally
                # generated - if it was first written under a different
                # event's content_language (e.g. cached in English, this
                # event is Dutch), it is NOT re-translated here. Same
                # "shared across events as-is" tradeoff CONFIG_CAVEATS.md
                # already documents for ENABLE_ENRICHMENT_REUSE generally -
                # not solved in this pass.
                age_days = (datetime.utcnow() - cached.last_enriched_at).days
                # Deep copy - never mutate cached.structured_profile itself,
                # that dict belongs to the EnrichedProfile row.
                profile = copy.deepcopy(cached.structured_profile)
                profile["person"]["looking_for"] = participant.looking_for
                profile["person"]["offerings"] = participant.offerings

                _record_job(
                    db,
                    participant.id,
                    EnrichmentSource.reused_from_cache,
                    {
                        "email": normalize_email(participant.email),
                        "last_enriched_at": cached.last_enriched_at.isoformat(),
                        "age_days": age_days,
                    },
                )
                participant.structured_profile = profile
                # Stale-cache guard: any prior translation of the old
                # summary is no longer valid for this new content.
                participant.profile_translations = None
                participant.enrichment_status = EnrichmentStatus.done
                _maybe_unlock_review_status(participant, profile)
                db.commit()

                _embed_and_store(db, participant, profile)

                return {"participant_id": participant_id, "status": "done", "reused": True}

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

        person_tavily = search_person(participant.name, participant.company)
        _record_job(db, participant.id, EnrichmentSource.tavily_person, person_tavily.get("snippets"))

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
            person_tavily=person_tavily,
        )

        source_urls = [
            *(company_data.get("tavily_web_sources") or []),
            *(company_data.get("tavily_news_sources") or []),
            *(person_tavily.get("sources") or []),
        ]
        if participant.website:
            source_urls.append(participant.website)

        try:
            profile = _normalize_with_one_extra_retry(
                merged_context,
                looking_for=participant.looking_for,
                offerings=participant.offerings,
                source_urls=source_urls,
                content_language=content_language,
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
        # Stale-cache guard: any prior translation of the old summary is no
        # longer valid for this new content.
        participant.profile_translations = None
        participant.enrichment_status = EnrichmentStatus.done
        _maybe_unlock_review_status(participant, profile)
        db.commit()

        upsert_enriched_profile(db, participant.email, profile)

        _embed_and_store(db, participant, profile)

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
