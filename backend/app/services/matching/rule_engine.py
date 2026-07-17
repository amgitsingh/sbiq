from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.participant import MembershipTier, Participant, ParticipantStatus
from app.services.matching.sector_size import company_size_score, sector_alignment_score
from app.services.matching.token_overlap import token_overlap_score
from app.services.similarity_search import find_similar_participants

# Composite weights per CLAUDE.md's confirmed formula:
# score = (token_overlap x 0.5) + (sector x 0.3) + (size x 0.2)
TOKEN_OVERLAP_WEIGHT = 0.5
SECTOR_WEIGHT = 0.3
SIZE_WEIGHT = 0.2

SIMILARITY_POOL_SIZE = 20  # Task 24's initial vector-search candidate pool
RESULT_TOP_N = 10  # narrowed shortlist size, per CLAUDE.md's "5-10 candidates"

# Sponsors processed first, then premium, then business/normal - per CLAUDE.md's
# Priority & Eligibility Rules table. Non-members are deliberately absent: they
# get 0 matches allocated (candidate-only), so they never receive a shortlist
# of their own, even though they can still appear *in* someone else's.
TIER_PROCESSING_ORDER = [
    MembershipTier.sponsor,
    MembershipTier.premium_member,
    MembershipTier.business_member,
    MembershipTier.normal_member,
]


def _normalize_company(name: str | None) -> str:
    return (name or "").strip().lower()


def score_pair(a: Participant, b: Participant) -> dict:
    """Composite rule-engine score for one candidate pair - symmetric, i.e.
    score_pair(a, b) == score_pair(b, a) in everything but which participant_id
    is reported, since every scorer feeding it is itself symmetric.

    Same-company pairs are hard-excluded (composite forced to 0, flagged) -
    two colleagues at the same company aren't a useful match on a platform
    meant for cross-company connections.
    """
    a_company = _normalize_company(a.company)
    b_company = _normalize_company(b.company)
    same_company = bool(a_company) and a_company == b_company
    if same_company:
        return {"composite_score": 0.0, "excluded_same_company": True}

    overlap = token_overlap_score(
        a_looking_for=a.looking_for,
        a_offerings=a.offerings,
        b_looking_for=b.looking_for,
        b_offerings=b.offerings,
    )
    sector = sector_alignment_score(a.sector, b.sector)
    size = company_size_score(a.company_size, b.company_size)
    composite = overlap * TOKEN_OVERLAP_WEIGHT + sector * SECTOR_WEIGHT + size * SIZE_WEIGHT

    return {
        "composite_score": composite,
        "token_overlap": overlap,
        "sector_score": sector,
        "size_score": size,
        "excluded_same_company": False,
    }


def _rank_for_participant(
    db: Session,
    participant: Participant,
    *,
    pair_cache: dict[frozenset[int], dict] | None = None,
    top_n: int = RESULT_TOP_N,
) -> list[dict]:
    similar = find_similar_participants(
        db, participant_id=participant.id, event_id=participant.event_id, top_n=SIMILARITY_POOL_SIZE
    )
    if not similar:
        return []

    candidate_ids = [row["participant_id"] for row in similar]
    candidates_by_id = {c.id: c for c in db.query(Participant).filter(Participant.id.in_(candidate_ids)).all()}

    scored = []
    for row in similar:
        candidate = candidates_by_id.get(row["participant_id"])
        if candidate is None:
            continue

        pair_key = frozenset((participant.id, candidate.id))
        result = pair_cache.get(pair_key) if pair_cache is not None else None
        if result is None:
            result = score_pair(participant, candidate)
            if pair_cache is not None:
                pair_cache[pair_key] = result

        if result["excluded_same_company"]:
            continue

        scored.append({**result, "participant_id": candidate.id, "similarity_score": row["similarity_score"]})

    scored.sort(key=lambda r: r["composite_score"], reverse=True)
    return scored[:top_n]


def rank_candidates(db: Session, *, participant: Participant, top_n: int = RESULT_TOP_N) -> list[dict]:
    """Single-participant entry point: similarity search -> composite score ->
    exclude same-company -> top N, ranked descending.
    """
    return _rank_for_participant(db, participant, top_n=top_n)


def run_rule_engine_for_event(db: Session, *, event_id: int) -> dict[int, list[dict]]:
    """Rank candidates for every eligible participant in an event.

    Skips two groups entirely as the *primary* subject (they never get a
    shortlist of their own) - both per CLAUDE.md's Priority & Eligibility
    Rules table:
    - non-members (0 matches allocated - candidate-only)
    - participants flagged for review (no looking_for and no offerings - "not
      auto-matched")
    Neither group is excluded from *other* participants' candidate pools -
    non-members can still appear as a candidate, and a review-flagged
    participant's blank intent fields already zero out their token overlap
    score naturally, so no extra filtering is needed there.

    Processes sponsors first, then premium, then business/normal (never
    non-members, per above). A pair's score is computed once and reused for
    both directions via pair_cache, since score_pair is symmetric - this is
    the "A->B = B->A counted once" deduplication from CLAUDE.md's rule engine
    bullets, applied as a computation-cache rather than a result exclusion
    (the same pair can legitimately appear in both participants' shortlists).
    """
    participants = (
        db.query(Participant)
        .filter(
            Participant.event_id == event_id,
            Participant.participant_status != ParticipantStatus.review,
        )
        .all()
    )
    by_tier: dict[str, list[Participant]] = {}
    for p in participants:
        by_tier.setdefault(p.membership_tier, []).append(p)

    pair_cache: dict[frozenset[int], dict] = {}
    results: dict[int, list[dict]] = {}

    for tier in TIER_PROCESSING_ORDER:
        for participant in by_tier.get(tier.value, []):
            results[participant.id] = _rank_for_participant(db, participant, pair_cache=pair_cache)

    return results
