from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.participant import EnrichmentStatus, MembershipTier, Participant, ParticipantStatus
from app.services.embedding import serialize_profile_to_text

# Rough English-text heuristic (~4 chars/token) - not a real tokenizer. This
# project has no tiktoken dependency; per CLAUDE.md's cost-visibility goal
# ("estimated cost shown before triggering a run"), a rough pre-run estimate
# is the point, not a precise bill. Good enough to catch a wildly oversized
# run before it's kicked off.
CHARS_PER_TOKEN = 4

# Worst-case candidate count per participant - the rule engine returns 5-10
# (Task 28), so pricing off the upper bound means this estimate errs high,
# never low, matching the "cost guardrail" spirit of AI_MAX_TOKENS_PER_RUN.
CANDIDATES_PER_PROMPT = 10

# Rough average LLM output size per participant: up to 5 matches x (3
# reasoning bullets + an email draft + a LinkedIn draft) worth of text. Not
# llm_matcher.MAX_RESPONSE_TOKENS (3_000) - that's a hard per-call ceiling,
# not a typical size, and using it here would badly overstate cost.
ESTIMATED_OUTPUT_TOKENS_PER_PARTICIPANT = 600

# USD per 1K tokens. Keyed by substring match against settings.AI_MODEL so
# common aliases ("gpt-4o", "gpt-4o-2026-01-01") still resolve. Falls back to
# the configured model's cheapest known neighbor if unrecognized - update
# this table whenever AI_MODEL changes to a model not listed here (see
# CONFIG_CAVEATS.md).
EMBEDDING_PRICE_PER_1K_TOKENS = 0.00002  # text-embedding-3-small

_LLM_PRICING_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    # model substring -> (input price, output price)
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-3.5": (0.0005, 0.0015),
}
_DEFAULT_LLM_PRICING = (0.0025, 0.01)  # gpt-4o-equivalent, used if AI_MODEL is unrecognized


def _llm_pricing() -> tuple[float, float]:
    model = settings.AI_MODEL.lower()
    for key, pricing in _LLM_PRICING_PER_1K_TOKENS.items():
        if key in model:
            return pricing
    return _DEFAULT_LLM_PRICING


# Non-members and review-flagged participants never trigger their own LLM
# matching call (Task 28's rule engine never generates a shortlist for them),
# so they're excluded from the LLM cost component - but not from the
# embedding cost component, since every enriched participant gets embedded
# regardless of tier/eligibility (Task 23).
_TIERS_ELIGIBLE_FOR_MATCHING = {
    MembershipTier.sponsor,
    MembershipTier.premium_member,
    MembershipTier.business_member,
    MembershipTier.normal_member,
}


def estimate_matching_run_cost(db: Session, *, event_id: int) -> dict:
    """Pre-run cost estimate for an event, per CLAUDE.md's cost-visibility
    goal: "estimated cost shown in admin panel before triggering matching run."

    Embedding cost is estimated against every enriched (enrichment_status =
    done) participant, since Task 23 embeds all of them unconditionally.
    LLM reasoning cost is estimated only against participants who'll actually
    receive a rule-engine shortlist and an LLM call - excludes non-members (0
    matches allocated) and review-flagged participants (not auto-matched),
    mirroring Task 28's own filtering exactly.

    Character lengths are real, computed from each participant's actual
    stored structured_profile via the same serialize_profile_to_text used to
    build the real embedding input (Task 22) - not a synthetic guess.
    """
    enriched = (
        db.query(Participant)
        .filter(Participant.event_id == event_id, Participant.enrichment_status == EnrichmentStatus.done)
        .all()
    )

    participant_count = len(enriched)
    if participant_count == 0:
        return {
            "participant_count": 0,
            "matching_eligible_count": 0,
            "embedding_cost_usd": 0.0,
            "llm_cost_usd": 0.0,
            "total_cost_usd": 0.0,
        }

    profile_texts = [serialize_profile_to_text(p.structured_profile or {}) for p in enriched]
    avg_chars = sum(len(t) for t in profile_texts) / len(profile_texts)
    avg_profile_tokens = avg_chars / CHARS_PER_TOKEN

    embedding_tokens = avg_profile_tokens * participant_count
    embedding_cost = (embedding_tokens / 1000) * EMBEDDING_PRICE_PER_1K_TOKENS

    matching_eligible_count = sum(
        1
        for p in enriched
        if p.membership_tier in _TIERS_ELIGIBLE_FOR_MATCHING and p.participant_status != ParticipantStatus.review
    )

    avg_prompt_tokens = avg_profile_tokens * (1 + CANDIDATES_PER_PROMPT)
    llm_input_price, llm_output_price = _llm_pricing()
    llm_input_cost = (avg_prompt_tokens * matching_eligible_count / 1000) * llm_input_price
    llm_output_cost = (
        ESTIMATED_OUTPUT_TOKENS_PER_PARTICIPANT * matching_eligible_count / 1000
    ) * llm_output_price
    llm_cost = llm_input_cost + llm_output_cost

    return {
        "participant_count": participant_count,
        "matching_eligible_count": matching_eligible_count,
        "embedding_cost_usd": round(embedding_cost, 4),
        "llm_cost_usd": round(llm_cost, 4),
        "total_cost_usd": round(embedding_cost + llm_cost, 4),
    }
