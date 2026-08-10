from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.match import Match
from app.services.matching.llm_matcher import ReverseDraftError, generate_reverse_draft

logger = logging.getLogger(__name__)


def _find_match(db: Session, *, event_id: int, participant_a_id: int, participant_b_id: int) -> Match | None:
    return (
        db.query(Match)
        .filter(
            Match.event_id == event_id,
            Match.participant_a_id == participant_a_id,
            Match.participant_b_id == participant_b_id,
        )
        .first()
    )


def store_match(
    db: Session,
    *,
    event_id: int,
    participant_a_id: int,
    participant_b_id: int,
    rank: int,
    score: float,
    reasoning: list[str],
    email_draft: str,
    linkedin_draft: str,
    participant_a_profile: dict | None = None,
    participant_b_profile: dict | None = None,
    event_context: str | None = None,
    content_language: str | None = None,
) -> Match:
    """Persist one LLM-selected match A->B, then enforce the confirmed
    architecture decision that matching is bidirectional: if A selects B, B
    automatically receives A too.

    Upserts on the ordered (event_id, participant_a_id, participant_b_id)
    triple, so a participant's matching run can be safely re-run without
    duplicating rows. Always sets is_bidirectional=False on this write - a
    direct store_match call always represents a genuine, independently
    selected match, never a mirror (mirrors are only ever created below).

    Reverse direction (B->A):
    - Doesn't exist yet: auto-create it, is_bidirectional=True, with rank and
      score mirrored (relationship-level facts, true regardless of
      direction). reasoning is mirrored too, per the confirmed decision -
      it's written about the pair, not addressed to either side specifically.
      email_draft/linkedin_draft are NOT mirrored - they're personalized and
      directional (A's outreach *to* B), so copying them onto B->A would put
      A's words in B's mouth. Instead, if both profiles are given, one extra
      LLM call (generate_reverse_draft) writes B's own genuine drafts to A
      right now, so this row isn't stuck null until/unless B's own
      independent matching run happens to reciprocate. Best-effort: on
      failure (or if profiles weren't passed - e.g. tests, or callers that
      don't have them), falls back to null, same as before.
    - Already exists (genuine or a prior placeholder): left untouched. This
      is the "A->B = B->A counted once" duplicate-prevention case - if B's
      run already produced (or later produces) its own genuine B->A match, it
      takes the normal upsert path above and is never clobbered by a lesser
      mirrored placeholder from this side.
    """
    existing = _find_match(db, event_id=event_id, participant_a_id=participant_a_id, participant_b_id=participant_b_id)
    if existing is not None:
        existing.rank = rank
        existing.score = score
        existing.reasoning = reasoning
        existing.email_draft = email_draft
        existing.linkedin_draft = linkedin_draft
        existing.is_bidirectional = False
        # Stale-cache guard: any prior translation of the old reasoning/
        # drafts is no longer valid for this new content (a re-run of
        # matching for this pair).
        existing.translations = None
        match = existing
    else:
        match = Match(
            event_id=event_id,
            participant_a_id=participant_a_id,
            participant_b_id=participant_b_id,
            rank=rank,
            score=score,
            reasoning=reasoning,
            email_draft=email_draft,
            linkedin_draft=linkedin_draft,
            is_bidirectional=False,
        )
        db.add(match)

    reverse = _find_match(db, event_id=event_id, participant_a_id=participant_b_id, participant_b_id=participant_a_id)
    if reverse is None:
        reverse_email_draft: str | None = None
        reverse_linkedin_draft: str | None = None
        if participant_a_profile is not None and participant_b_profile is not None:
            try:
                draft = generate_reverse_draft(
                    sender_profile=participant_b_profile,
                    recipient_profile=participant_a_profile,
                    reasoning=reasoning,
                    event_context=event_context,
                    content_language=content_language,
                )
                reverse_email_draft = draft["email_draft"]
                reverse_linkedin_draft = draft["linkedin_draft"]
            except ReverseDraftError as e:
                logger.warning(
                    f"Reverse draft generation failed for match "
                    f"{event_id}/{participant_b_id}->{participant_a_id}, leaving drafts null: {e}"
                )

        db.add(
            Match(
                event_id=event_id,
                participant_a_id=participant_b_id,
                participant_b_id=participant_a_id,
                rank=rank,
                score=score,
                reasoning=reasoning,
                email_draft=reverse_email_draft,
                linkedin_draft=reverse_linkedin_draft,
                is_bidirectional=True,
            )
        )

    db.commit()
    return match
