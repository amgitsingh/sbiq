from __future__ import annotations

import json
import logging

from app.models.event import Event
from app.services.ai_client import chat_json_with_usage
from app.services.json_utils import strip_markdown_fence
from app.services.matching.match_schema import MatchSelection

logger = logging.getLogger(__name__)

MAX_RESPONSE_TOKENS = 3_000
MAX_ATTEMPTS = 2
MAX_MATCHES = 5

SYSTEM_PROMPT = """You are a business matchmaking assistant for an event networking \
platform. You will be given one participant's profile and a shortlist of candidate \
profiles that a deterministic rule engine has already pre-filtered for them, along \
with each candidate's rule-engine score. Your job is to select the best matches from \
this shortlist and write a short rationale and outreach drafts for each.

You may also be given an EVENT CONTEXT section describing this specific event's \
purpose and matchmaking goals - when present, weigh it when judging fit and let it \
inform your reasoning bullets and drafts, not just the two participants' profiles.

Respond with a single JSON object with exactly this shape:
{
  "matches": [
    {
      "participant_id": <int, MUST be one of the candidate IDs given>,
      "rank": <int, 1 = best match, no gaps or duplicates>,
      "reasoning": [<exactly 3 short bullet strings explaining why this is a good match>],
      "email_draft": <a short, personalized introduction email from the participant to \
this candidate, referencing specific shared interest or complementary offering>,
      "linkedin_draft": <a short LinkedIn connection request message, 1-2 sentences>
    }
  ]
}

Rules:
- Select between 0 and 5 matches - only the ones genuinely worth introducing. If none \
of the candidates are a good fit, return an empty matches list rather than forcing a \
bad match.
- "participant_id" must always be one of the candidate IDs given above - never invent one.
- Rank matches 1 (best) through N with no gaps or duplicates.
- Reasoning bullets must reference concrete details from both profiles - no generic filler.
- "email_draft" and "linkedin_draft" must be written from the participant's perspective, \
addressed to the candidate by name.
- Respond with a single JSON object only, matching the shape above exactly. No markdown, \
no commentary."""


class MatchSelectionError(Exception):
    """Raised when the LLM never produced a valid match selection after retrying."""


def _format_profile(profile: dict) -> str:
    person = (profile or {}).get("person") or {}
    company = (profile or {}).get("company") or {}
    lines: list[str] = []

    def add(label: str, value) -> None:
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if value:
            lines.append(f"{label}: {value}")

    add("Name", person.get("name"))
    add("Designation", person.get("designation"))
    add("Looking for", person.get("looking_for"))
    add("Offerings", person.get("offerings"))
    add("Company", company.get("name"))
    add("Industry", company.get("industry"))
    add("Employee count", company.get("employee_count"))
    add("Summary", company.get("summary"))
    return "\n".join(lines)


def build_event_context(event: Event) -> str | None:
    """Assemble a short event-context block from agenda/matching_goals/
    target_sectors, for prepending to the matching prompt. Returns None if
    all three are blank, so callers can skip the section entirely rather
    than emit an empty/pointless header.
    """
    lines: list[str] = []
    if event.agenda:
        lines.append(f"Agenda: {event.agenda}")
    if event.matching_goals:
        lines.append(f"Matching goals: {event.matching_goals}")
    if event.target_sectors:
        lines.append(f"Target sectors: {', '.join(event.target_sectors)}")
    return "\n".join(lines) if lines else None


def build_matching_prompt(
    participant_profile: dict, candidates: list[dict], event_context: str | None = None
) -> str:
    """candidates: [{"participant_id", "profile", "composite_score",
    "token_overlap", "sector_score", "size_score"}, ...] - rule_engine.py's
    output shape, joined with each candidate's structured_profile by the caller.

    event_context: pre-built via build_event_context() - kept as a plain
    string param here (rather than accepting the Event itself) so this
    function stays testable without a real Event/DB object.
    """
    lines: list[str] = []
    if event_context:
        lines.extend(["=== EVENT CONTEXT ===", event_context, ""])

    lines += ["=== PARTICIPANT (selecting matches for this person) ===", _format_profile(participant_profile), ""]

    lines.append("=== CANDIDATES (pre-filtered by the rule engine) ===")
    for c in candidates:
        lines.append(f"--- Candidate ID: {c['participant_id']} ---")
        lines.append(_format_profile(c["profile"]))
        lines.append(
            f"Rule-engine score: {c['composite_score']:.2f} "
            f"(token_overlap={c['token_overlap']:.2f}, sector={c['sector_score']:.2f}, "
            f"size={c['size_score']:.2f})"
        )
        lines.append("")

    return "\n".join(lines)


def _validate_selection(selection: MatchSelection, valid_ids: set[int]) -> None:
    if len(selection.matches) > MAX_MATCHES:
        raise ValueError(f"LLM returned {len(selection.matches)} matches, max is {MAX_MATCHES}")

    seen_ids: set[int] = set()
    seen_ranks: set[int] = set()
    for m in selection.matches:
        if m.participant_id not in valid_ids:
            raise ValueError(f"LLM selected participant_id {m.participant_id}, not in candidate pool")
        if m.participant_id in seen_ids:
            raise ValueError(f"Duplicate participant_id {m.participant_id} in match selection")
        seen_ids.add(m.participant_id)

        if m.rank in seen_ranks:
            raise ValueError(f"Duplicate rank {m.rank} in match selection")
        seen_ranks.add(m.rank)

        if len(m.reasoning) != 3:
            raise ValueError(
                f"Expected exactly 3 reasoning bullets for participant_id {m.participant_id}, "
                f"got {len(m.reasoning)}"
            )

    if seen_ranks and sorted(seen_ranks) != list(range(1, len(seen_ranks) + 1)):
        raise ValueError(f"Ranks must be a contiguous sequence starting at 1, got {sorted(seen_ranks)}")


def select_matches(
    participant_profile: dict, candidates: list[dict], event_context: str | None = None
) -> list[dict]:
    """Send a participant's profile + their rule-engine candidate shortlist to
    the LLM (JSON mode enforced) and return the selected matches as plain
    dicts. Retries once on any failure - invalid JSON, schema validation
    failure, or a business-rule violation (bad participant_id, duplicate
    rank, wrong reasoning-bullet count). Raises MatchSelectionError if both
    attempts fail.

    Returns [] immediately, with no LLM call, if given no candidates - nothing
    to select from.

    event_context: see build_event_context() - passed through untouched to
    build_matching_prompt.
    """
    if not candidates:
        return []

    valid_ids = {c["participant_id"] for c in candidates}
    user_prompt = build_matching_prompt(participant_profile, candidates, event_context)

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw, usage = chat_json_with_usage(SYSTEM_PROMPT, user_prompt, max_tokens=MAX_RESPONSE_TOKENS)
            logger.info(
                f"Match selection attempt {attempt}: input_tokens={usage['input_tokens']} "
                f"output_tokens={usage['output_tokens']}"
            )
            parsed = json.loads(strip_markdown_fence(raw))
            selection = MatchSelection.model_validate(parsed)
            _validate_selection(selection, valid_ids)
        except Exception as e:
            last_error = e
            logger.warning(f"Match selection attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            continue

        return [m.model_dump() for m in selection.matches]

    raise MatchSelectionError(
        f"Match selection failed after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
