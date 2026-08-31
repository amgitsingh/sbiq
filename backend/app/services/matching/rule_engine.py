from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.participant import MembershipTier, Participant, ParticipantStatus
from app.services.matching.decision_authority import decision_authority_score
from app.services.matching.ecosystem_role import role_adjacency_score
from app.services.matching.sector_size import company_size_score, sector_alignment_score
from app.services.matching.token_overlap import token_overlap_score
from app.services.similarity_search import find_similar_participants

# Composite weights - role adjacency is the dominant factor, since it's the
# one signal that catches complementary-but-dissimilar pairs (a luxury
# logistics company paired with a capital-access firm, a hotel group paired
# with a bank) that token_overlap/sector/size structurally miss - confirmed
# empirically against real client-approved matches that scored near-zero on
# the old 3-factor formula. See docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md, Item 2.
# The original three are de-weighted, not zeroed - still real signal for
# genuinely similar-and-compatible pairs.
ROLE_ADJACENCY_WEIGHT = 0.40
TOKEN_OVERLAP_WEIGHT = 0.25
SECTOR_WEIGHT = 0.15
SIZE_WEIGHT = 0.10
DECISION_AUTHORITY_WEIGHT = 0.10

SIMILARITY_POOL_SIZE = 20  # Task 24's initial vector-search candidate pool
RESULT_TOP_N = 10  # narrowed shortlist size, per CLAUDE.md's "5-10 candidates"

# Sponsors processed first, then premium, then business/normal, then
# non-member last. Non-member was originally deliberately absent here (0
# matches allocated, candidate-only) per CLAUDE.md's Priority & Eligibility
# Rules table - real client feedback found that left too large a share of a
# real participant list (38% on one real event) permanently un-matchable,
# so non-members now get a capped quota of NON_MEMBER_MATCH_QUOTA instead
# of zero (see matching_tasks.match_participant, which enforces the cap
# after the LLM's normal selection). Still processed last/lowest priority.
TIER_PROCESSING_ORDER = [
    MembershipTier.sponsor,
    MembershipTier.premium_member,
    MembershipTier.business_member,
    MembershipTier.normal_member,
    MembershipTier.non_member,
]

# Non-members' match cap - a deliberately small taste of the platform's
# value (vs. 0 before) rather than parity with paying tiers, preserving the
# membership-tier incentive to upgrade. Enforced in matching_tasks.py after
# the LLM's own 0-5 selection, not by asking the LLM for fewer - keeps the
# LLM prompt/schema tier-agnostic.
NON_MEMBER_MATCH_QUOTA = 1


def _normalize_company(name: str | None) -> str:
    return (name or "").strip().lower()


def _ecosystem_role(p: Participant) -> str | None:
    return (p.structured_profile or {}).get("ecosystem_role")


def _company_size(p: Participant) -> str | None:
    """participant.company_size verbatim (from Excel), falling back to
    enrichment's structured_profile.company.employee_count when the raw
    ingested column is empty.

    Real-world gap this closes: company_size is only ever set at ingestion
    time from a mapped Excel column - if the source file has no such column
    (confirmed for real against event 35, where all 75 rows have
    company_size=None), company_size_score silently returns 0.0 for every
    single pair, permanently zeroing out its full SIZE_WEIGHT share of the
    composite even though enrichment already fetched a usable employee count
    for a meaningful fraction of participants (Crunchbase/website/LinkedIn,
    per CLAUDE.md's enrichment field mapping) that was simply never consulted
    here. _parse_employee_count already tolerates free text (ranges, "FTE"/
    "medewerkers" suffixes, thousands commas), so no extra parsing is needed.
    """
    return p.company_size or (p.structured_profile or {}).get("company", {}).get("employee_count")


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
    size = company_size_score(_company_size(a), _company_size(b))
    role_adjacency = role_adjacency_score(_ecosystem_role(a), _ecosystem_role(b))
    decision_authority = decision_authority_score(a.designation, b.designation)
    composite = (
        overlap * TOKEN_OVERLAP_WEIGHT
        + sector * SECTOR_WEIGHT
        + size * SIZE_WEIGHT
        + role_adjacency * ROLE_ADJACENCY_WEIGHT
        + decision_authority * DECISION_AUTHORITY_WEIGHT
    )

    return {
        "composite_score": composite,
        "token_overlap": overlap,
        "sector_score": sector,
        "size_score": size,
        "role_adjacency_score": role_adjacency,
        "decision_authority_score": decision_authority,
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

    Skips participants flagged for review as the *primary* subject (they
    never get a shortlist of their own) - blank looking_for/offerings (or
    tier ambiguity, or an unresolved duplicate submission) means "not
    auto-matched" per CLAUDE.md's Priority & Eligibility Rules table. Not
    excluded from *other* participants' candidate pools though - a
    review-flagged participant's blank intent fields already zero out their
    token overlap score naturally, so no extra filtering is needed there.
    (enrichment_tasks.py can later flip a blank-intent-fields-only review
    flag back to eligible once real enrichment signal is found - see
    _maybe_unlock_review_status - after which this function treats them
    normally.)

    Non-members ARE included as a primary subject (unlike the above) - capped
    to NON_MEMBER_MATCH_QUOTA post-selection in matching_tasks.py, not
    excluded here entirely. Processes sponsors first, then premium, then
    business/normal, then non-member last (TIER_PROCESSING_ORDER). A pair's
    score is computed once and reused for both directions via pair_cache,
    since score_pair is symmetric - this is the "A->B = B->A counted once"
    deduplication from CLAUDE.md's rule engine bullets, applied as a
    computation-cache rather than a result exclusion (the same pair can
    legitimately appear in both participants' shortlists).
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
