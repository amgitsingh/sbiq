"""LLM match selection + reasoning.

Note: this module does NOT generate a free-form "email_draft" - it did
originally, but that content was superseded by
app/services/matching/participant_email_composer.py's deterministic,
docs/mail-template.docx-formatted email (real user request: the actual
sent email must match that template, not free LLM prose). Keeping the LLM
generate an email nobody sends would be pure wasted cost/latency, so
"email_draft" was removed from both MatchItem and ReverseDraft entirely -
reasoning/reciprocal_reason/linkedin_draft are the only per-match LLM
output now. linkedin_draft is still LLM-authored and still used verbatim
(the template's "LinkedIn introduction - copy & paste" section).
"""
from __future__ import annotations

import json
import logging

from app.models.event import Event
from app.services.ai_client import chat_json_with_usage
from app.services.json_utils import strip_markdown_fence
from app.services.matching.match_schema import MatchSelection, ReverseDraft

logger = logging.getLogger(__name__)

# Raised from 3_000 when drafts were first written in more detail; lowered
# back down after email_draft was dropped from this prompt entirely (the
# real send email is now composed deterministically - see
# app/services/matching/participant_email_composer.py - not LLM-authored),
# leaving reasoning/reciprocal_reason/linkedin_draft as the only per-match
# output, which need less headroom than before.
MAX_RESPONSE_TOKENS = 3_000
MAX_ATTEMPTS = 2
# Fallback only, for a caller that doesn't specify max_matches (e.g. an ad
# hoc script) - every real call site (matching_tasks.py) passes an explicit
# per-tier ceiling instead (rule_engine.MATCH_QUOTA_BY_TIER: real
# client-specified numbers - Sponsor up to 3, Premium up to 2, Business/
# Normal up to 1). Comfortably under rule_engine.RESULT_TOP_N=10 (the full
# shortlist size the LLM ever sees) either way.
DEFAULT_MAX_MATCHES = 5
# Reverse-draft calls only ever produce one match's worth of content (no
# reasoning, no candidate list) - a fraction of MAX_RESPONSE_TOKENS.
REVERSE_DRAFT_MAX_RESPONSE_TOKENS = 800

# {MAX_MATCHES} is substituted via a plain string .replace() at call time
# (_build_system_prompt), not str.format() - this template's JSON schema
# block below is full of literal { } that would need escaping for
# .format() to work, so a unique sentinel token + .replace() sidesteps
# that entirely.
SYSTEM_PROMPT_TEMPLATE = """You are a business matchmaking assistant for an event networking \
platform. You will be given one participant's profile and a shortlist of candidate \
profiles that a deterministic rule engine has already pre-filtered for them, along \
with each candidate's rule-engine score. Your job is to select the best matches from \
this shortlist and write a short rationale and outreach drafts for each.

You may also be given an EVENT CONTEXT section describing this specific event's \
purpose and matchmaking goals - when present, weigh it when judging fit and let it \
inform your reasoning bullets and drafts, not just the two participants' profiles.

Prefer including a plausible match over excluding it. A rule engine has already \
pre-filtered this shortlist for you - every candidate on it cleared a real relevance bar, \
so most candidates here deserve inclusion. Only leave a candidate out if there is truly no \
reasonable commercial, complementary, or strategic connection you can articulate - not \
because the connection is merely modest. When genuinely unsure, include it with honest, \
measured reasoning rather than omitting it.

Respond with a single JSON object with exactly this shape:
{
  "matches": [
    {
      "participant_id": <int, MUST be one of the candidate IDs given>,
      "rank": <int, 1 = best match, no gaps or duplicates>,
      "reasoning": [<EXACTLY 3 short bullet strings, in this fixed order and meaning - \
never reorder or merge them: \
(1) a concrete COMMERCIAL opportunity - e.g. a plausible client, revenue, or sales \
relationship between them; \
(2) COMPLEMENTARY EXPERTISE - specific skills, services, or network each side has that \
would strengthen the other; \
(3) a STRATEGIC opportunity - potential partnership, collaboration, growth, innovation, \
or access to a relevant network.>],
      "reciprocal_reason": <one specific sentence describing why the PARTICIPANT would be \
valuable *to the candidate*, grounded in the participant's own expertise, network, \
customers, market position, or offerings - the reverse direction of "reasoning" above. \
CRITICAL: this text is shown to the PARTICIPANT (explaining their own value to the \
candidate), never sent to the candidate directly - so write it in THIRD PERSON, always \
naming the candidate explicitly (e.g. "Jane Doe would gain..." / "This could give Acme \
Corp..."), and NEVER use "you"/"your" to mean the candidate. Do not confuse this with \
addressing the candidate as if writing to them.>,
      "linkedin_draft": <a short, specific LinkedIn connection message, 2-4 sentences \
(roughly 40-80 words), written as if the PARTICIPANT is sending it to the CANDIDATE: a \
brief self-introduction, naming the event and that they were matched via SBIQ.ai, one \
specific reason for the match, and a suggestion to connect/chat at or before the event. \
This is used verbatim as copy-paste text the participant sends themselves - keep it \
natural and personal, not corporate.>
    }
  ]
}

Rules:
- Select up to {MAX_MATCHES} matches. Default toward including a candidate rather than \
excluding it, per the guidance above - an empty or near-empty list should be rare, reserved \
for cases with genuinely no plausible connection anywhere in the shortlist. {MAX_MATCHES} is \
a ceiling, not a target - never invent a weaker match just to reach it.
- "participant_id" must always be one of the candidate IDs given above - never invent one.
- Rank matches 1 (best) through N with no gaps or duplicates.
- Reasoning bullets must reference concrete details from both profiles - no generic filler.
- "reciprocal_reason" must be genuinely about the participant's value to the candidate, \
not a restatement of "reasoning" (which is about the candidate's value to the participant). \
Write it in third person naming the candidate - never "you"/"your" addressed to the candidate.
- "linkedin_draft" must be written from the participant's perspective, addressed to the \
candidate by name, and must meet the length/structure guidance above - never a one-line or \
generic-filler draft.
- Respond with a single JSON object only, matching the shape above exactly. No markdown, \
no commentary."""


def _build_system_prompt(max_matches: int) -> str:
    return SYSTEM_PROMPT_TEMPLATE.replace("{MAX_MATCHES}", str(max_matches))


# Only Dutch needs an entry - English is the prompt's implicit default, so
# content_language=None/"en" appends nothing (no behavior change for
# existing events). Keyed by Event.content_language's exact values. Same
# convention as llm_normalizer._language_directive - kept as a separate small
# copy here rather than a shared helper, since the two prompts' wording
# (which fields to write in that language) genuinely differs.
LANGUAGE_NAMES = {"nl": "Dutch"}


def _language_directive(content_language: str | None) -> str | None:
    name = LANGUAGE_NAMES.get(content_language or "")
    if not name:
        return None
    return f'Write "reasoning", "reciprocal_reason", and "linkedin_draft" in {name}, not English.'


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


def _validate_selection(selection: MatchSelection, valid_ids: set[int], max_matches: int) -> None:
    if len(selection.matches) > max_matches:
        raise ValueError(f"LLM returned {len(selection.matches)} matches, max is {max_matches}")

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

        if not m.reciprocal_reason or not m.reciprocal_reason.strip():
            raise ValueError(f"Empty reciprocal_reason for participant_id {m.participant_id}")

    if seen_ranks and sorted(seen_ranks) != list(range(1, len(seen_ranks) + 1)):
        raise ValueError(f"Ranks must be a contiguous sequence starting at 1, got {sorted(seen_ranks)}")


def select_matches(
    participant_profile: dict,
    candidates: list[dict],
    event_context: str | None = None,
    content_language: str | None = None,
    max_matches: int = DEFAULT_MAX_MATCHES,
) -> list[dict]:
    """Send a participant's profile + their rule-engine candidate shortlist to
    the LLM (JSON mode enforced) and return the selected matches as plain
    dicts. Retries once on any failure - invalid JSON, schema validation
    failure, or a business-rule violation (bad participant_id, duplicate
    rank, wrong reasoning-bullet count, or exceeding max_matches). Raises
    MatchSelectionError if both attempts fail.

    Returns [] immediately, with no LLM call, if given no candidates - nothing
    to select from.

    event_context: see build_event_context() - passed through untouched to
    build_matching_prompt.

    content_language: "en"/"nl"/None (Event.content_language) - affects
    reasoning/reciprocal_reason/linkedin_draft only.

    max_matches: this participant's own tier ceiling (real client-specified
    numbers - see rule_engine.MATCH_QUOTA_BY_TIER), substituted into the
    prompt and enforced by _validate_selection - NOT a post-hoc truncation,
    the LLM is asked for at most this many and a response exceeding it is
    treated as a validation failure (retried once, then raises).
    """
    if not candidates:
        return []

    valid_ids = {c["participant_id"] for c in candidates}
    user_prompt = build_matching_prompt(participant_profile, candidates, event_context)
    language_directive = _language_directive(content_language)
    base_prompt = _build_system_prompt(max_matches)
    system_prompt = f"{base_prompt}\n\n{language_directive}" if language_directive else base_prompt

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw, usage = chat_json_with_usage(system_prompt, user_prompt, max_tokens=MAX_RESPONSE_TOKENS)
            logger.info(
                f"Match selection attempt {attempt}: input_tokens={usage['input_tokens']} "
                f"output_tokens={usage['output_tokens']}"
            )
            parsed = json.loads(strip_markdown_fence(raw))
            selection = MatchSelection.model_validate(parsed)
            _validate_selection(selection, valid_ids, max_matches)
        except Exception as e:
            last_error = e
            logger.warning(f"Match selection attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            continue

        return [m.model_dump() for m in selection.matches]

    raise MatchSelectionError(
        f"Match selection failed after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error


REVERSE_DRAFT_SYSTEM_PROMPT = """You are a business matchmaking assistant for an event \
networking platform. A deterministic pipeline has already decided that two participants \
are a good match and produced the reasoning bullets below, written from the first \
participant's (the "sender") perspective. Your only job is to write that sender's own \
outreach drafts to the second participant (the "recipient") - do not re-evaluate whether \
they are a good match, that decision is already made.

Respond with a single JSON object with exactly this shape:
{
  "reciprocal_reason": <one specific sentence describing why the SENDER would be valuable \
*to the recipient*, grounded in the sender's own expertise, network, customers, market \
position, or offerings. Do not just restate the reasoning bullets given (those are about \
the recipient's value to the sender, the reverse direction). CRITICAL: this text is shown \
to the SENDER (explaining their own value to the recipient), never sent to the recipient \
directly - so write it in THIRD PERSON, always naming the recipient explicitly (e.g. "Jane \
Doe would gain..." / "This could give Acme Corp..."), and NEVER use "you"/"your" to mean \
the recipient.>,
  "linkedin_draft": <a short, specific LinkedIn connection message, 2-4 sentences \
(roughly 40-80 words), written as if the SENDER is sending it to the RECIPIENT: a brief \
self-introduction, naming the event and that they were matched via SBIQ.ai, one specific \
reason for the match, and a suggestion to connect/chat at or before the event. This is \
used verbatim as copy-paste text the sender sends themselves - keep it natural and \
personal, not corporate.>
}

Rules:
- Write from the sender's perspective, addressed to the recipient by name.
- Ground linkedin_draft in the reasoning bullets given - don't contradict them or invent a \
different rationale for why the match works.
- "reciprocal_reason" is about the sender's value to the recipient - the reverse of the \
reasoning bullets given - not a restatement of them. Write it in third person naming the \
recipient - never "you"/"your" addressed to the recipient.
- Meet the length/structure guidance above - never a one-line or generic-filler draft.
- Respond with a single JSON object only, matching the shape above exactly. No markdown, \
no commentary."""


def build_reverse_draft_prompt(
    sender_profile: dict, recipient_profile: dict, reasoning: list[str], event_context: str | None = None
) -> str:
    lines: list[str] = []
    if event_context:
        lines.extend(["=== EVENT CONTEXT ===", event_context, ""])
    lines += ["=== SENDER (writing the drafts) ===", _format_profile(sender_profile), ""]
    lines += ["=== RECIPIENT (drafts are addressed to them) ===", _format_profile(recipient_profile), ""]
    lines.append("=== WHY THIS IS A MATCH (already decided, do not re-evaluate) ===")
    lines.extend(f"- {bullet}" for bullet in reasoning)
    return "\n".join(lines)


class ReverseDraftError(Exception):
    """Raised when the LLM never produced a valid reverse draft after retrying."""


def generate_reverse_draft(
    sender_profile: dict,
    recipient_profile: dict,
    reasoning: list[str],
    event_context: str | None = None,
    content_language: str | None = None,
) -> dict:
    """Write the sender's own reciprocal_reason/linkedin_draft to the recipient,
    for the auto-created bidirectional mirror side of a match (see
    match_writer.store_match). The match itself and its reasoning are already
    decided by the forward direction's select_matches() call - this only
    fills in the missing personalized content so the mirror row isn't left
    null until/unless the recipient's own independent matching run happens
    to reciprocate.

    Retries once, same pattern as select_matches. Raises ReverseDraftError if
    both attempts fail - callers should treat that as non-fatal (log and leave
    the drafts null) since the primary match this mirrors was already written
    successfully.
    """
    user_prompt = build_reverse_draft_prompt(sender_profile, recipient_profile, reasoning, event_context)
    language_directive = _language_directive(content_language)
    system_prompt = (
        f"{REVERSE_DRAFT_SYSTEM_PROMPT}\n\n{language_directive}"
        if language_directive
        else REVERSE_DRAFT_SYSTEM_PROMPT
    )

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw, usage = chat_json_with_usage(
                system_prompt, user_prompt, max_tokens=REVERSE_DRAFT_MAX_RESPONSE_TOKENS
            )
            logger.info(
                f"Reverse draft attempt {attempt}: input_tokens={usage['input_tokens']} "
                f"output_tokens={usage['output_tokens']}"
            )
            parsed = json.loads(strip_markdown_fence(raw))
            draft = ReverseDraft.model_validate(parsed)
        except Exception as e:
            last_error = e
            logger.warning(f"Reverse draft attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            continue

        return draft.model_dump()

    raise ReverseDraftError(f"Reverse draft failed after {MAX_ATTEMPTS} attempts: {last_error}") from last_error
