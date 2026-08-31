import logging
from typing import cast

from app.core.database import session_scope
from app.models.event import Event
from app.models.participant import MatchingStatus, MembershipTier, Participant, ParticipantStatus
from app.models.participant_embedding import ParticipantEmbedding
from app.services.matching.llm_matcher import MatchSelectionError, build_event_context, select_matches
from app.services.matching.match_writer import store_match
from app.services.matching.rule_engine import TIER_PROCESSING_ORDER, rank_candidates
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.matching_tasks.match_participant",
    bind=True,
    queue="matching",
)
def match_participant(self, participant_id: int, event_id: int) -> dict:
    """Run the matching pipeline for one participant: similarity search ->
    rule engine -> LLM reasoning -> store match records -> enforce
    bidirectional (Tasks 24, 28, 29, 30 respectively).

    Also fetches the parent Event and, if it has any of agenda/
    matching_goals/target_sectors set, feeds them to the LLM as event context
    (see llm_matcher.build_event_context) so reasoning/drafts are grounded in
    this event's actual purpose, not generated from participant profiles alone.

    Skips (doesn't fail) non-members and review-flagged participants even if
    called directly - same eligibility rule Task 28's batch entry point
    enforces, kept here too since this task can be invoked on its own, not
    only via batch_match_event.

    No Celery-level autoretry - llm_matcher.select_matches already retries
    once internally, and everything else here (rule engine, DB writes) is
    free/local/deterministic, so a second full-task retry would only risk
    duplicating LLM spend for no benefit. A genuine failure is recorded via
    matching_status=failed and re-raised.
    """
    with session_scope() as db:
        participant = db.get(Participant, participant_id)
        if participant is None:
            raise ValueError(f"Participant {participant_id} not found")

        if (
            participant.membership_tier == MembershipTier.non_member
            or participant.participant_status == ParticipantStatus.review
        ):
            return {"participant_id": participant_id, "status": "skipped", "reason": "not eligible for matching"}

        if not participant.structured_profile:
            return {"participant_id": participant_id, "status": "skipped", "reason": "not enriched"}
        # Reassigned as a plain local + cast: Pylance doesn't retain the
        # narrowing from the truthy check above across the intervening
        # db.commit()/rank_candidates() calls on a Mapped[dict | None]
        # attribute, so a cast is the reliable way to say what's already
        # true at runtime - same pattern as cache.py's Redis narrowing.
        structured_profile = cast(dict, participant.structured_profile)

        participant.matching_status = MatchingStatus.matching
        db.commit()

        candidates = rank_candidates(db, participant=participant)
        if not candidates:
            participant.matching_status = MatchingStatus.done
            db.commit()
            return {"participant_id": participant_id, "status": "done", "matches": 0}

        candidate_ids = [c["participant_id"] for c in candidates]
        candidate_participants = {
            p.id: p for p in db.query(Participant).filter(Participant.id.in_(candidate_ids)).all()
        }
        candidates_with_profile = [
            {**c, "profile": candidate_participants[c["participant_id"]].structured_profile}
            for c in candidates
            if c["participant_id"] in candidate_participants
        ]

        event = db.get(Event, event_id)
        event_context = build_event_context(event) if event else None

        content_language = event.content_language if event else None

        try:
            selected = select_matches(structured_profile, candidates_with_profile, event_context, content_language)
        except MatchSelectionError as e:
            logger.warning(f"Match selection failed for participant {participant_id}: {e}")
            participant.matching_status = MatchingStatus.failed
            db.commit()
            raise

        composite_by_id = {c["participant_id"]: c["composite_score"] for c in candidates}
        profile_by_id = {c["participant_id"]: c["profile"] for c in candidates_with_profile}
        for m in selected:
            store_match(
                db,
                event_id=event_id,
                participant_a_id=participant.id,
                participant_b_id=m["participant_id"],
                rank=m["rank"],
                score=composite_by_id[m["participant_id"]],
                reasoning=m["reasoning"],
                reciprocal_reason=m["reciprocal_reason"],
                email_draft=m["email_draft"],
                linkedin_draft=m["linkedin_draft"],
                participant_a_profile=structured_profile,
                participant_b_profile=profile_by_id.get(m["participant_id"]),
                event_context=event_context,
                content_language=content_language,
            )

        participant.matching_status = MatchingStatus.done
        db.commit()
        return {"participant_id": participant_id, "status": "done", "matches": len(selected)}


@celery_app.task(
    name="app.workers.matching_tasks.batch_match_event",
    bind=True,
    queue="matching",
)
def batch_match_event(self, event_id: int) -> dict:
    """Fan out match_participant for every embedded, matching-eligible
    participant in an event, sponsors first (TIER_PROCESSING_ORDER - same
    priority order Task 28's rule engine batch entry point uses). Non-members
    and review-flagged participants are never dispatched at all - they get 0
    matches allocated / aren't auto-matched, per CLAUDE.md's Priority &
    Eligibility Rules table.

    "Embedded" is enforced with a join against participant_embeddings rather
    than trusting enrichment_status alone - a participant can be
    enrichment_status=done with no embedding yet if Task 23's automatic
    embedding attempt failed and hasn't been retried via Task 25.
    """
    with session_scope() as db:
        participants = (
            db.query(Participant)
            .join(
                ParticipantEmbedding,
                (ParticipantEmbedding.participant_id == Participant.id)
                & (ParticipantEmbedding.event_id == Participant.event_id),
            )
            .filter(
                Participant.event_id == event_id,
                Participant.participant_status != ParticipantStatus.review,
            )
            .all()
        )

        by_tier: dict[str, list[int]] = {}
        for p in participants:
            if p.membership_tier == MembershipTier.non_member:
                continue
            by_tier.setdefault(p.membership_tier, []).append(p.id)

    dispatched = 0
    for tier in TIER_PROCESSING_ORDER:
        for participant_id in by_tier.get(tier.value, []):
            match_participant.delay(participant_id, event_id)
            dispatched += 1

    return {"event_id": event_id, "dispatched": dispatched}
