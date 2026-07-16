from __future__ import annotations

import json
import logging

from app.services.ai_client import chat_json
from app.services.enrichment.profile_schema import StructuredProfile

logger = logging.getLogger(__name__)

MAX_RESPONSE_TOKENS = 1_500
MAX_ATTEMPTS = 2

SYSTEM_PROMPT = """You are a data normalization assistant for an event matchmaking \
platform. You will be given a block of raw context about one event participant: \
their own Excel-submitted fields, plus whatever public data was found about their \
company (website text, web search snippets, news, Crunchbase data) and their \
LinkedIn profile. Some sections may be missing - that source simply returned nothing.

Synthesize this into a single JSON object with exactly this shape:
{
  "person": {
    "name": string or null,
    "designation": string or null,
    "looking_for": string or null,
    "offerings": string or null
  },
  "company": {
    "name": string or null,
    "website": string or null,
    "industry": string or null,
    "products": [string],
    "services": [string],
    "markets": [string],
    "customers": [string],
    "technologies": [string],
    "employee_count": string or null,
    "headquarters": string or null,
    "funding_stage": string or null,
    "investors": [string],
    "recent_news": [string],
    "summary": string or null
  }
}

Rules:
- Fill every field you can reasonably support from the given context. Use null or an \
empty list for anything not mentioned anywhere - never invent facts.
- "company.summary" should be a short synthesis of everything known about the \
company, in your own words.
- Prefer the participant's own Excel-submitted values for "person.name" and \
"person.designation" over any conflicting value from LinkedIn or elsewhere.
- Copy "person.looking_for" and "person.offerings" through EXACTLY as given in the \
participant's Excel section, character for character, with no rewording, \
summarizing, or translation. Do not use other sections to fill these two fields in \
if the Excel section leaves them blank - leave them null instead.
- Respond with a single JSON object only, matching the shape above exactly. No \
markdown, no commentary."""


class ProfileNormalizationError(Exception):
    """Raised when the LLM never produced a schema-valid profile after retrying."""


def normalize_participant_profile(
    merged_context: str, *, looking_for: str | None, offerings: str | None
) -> dict:
    """Send one participant's merged enrichment context (Task 18's output) to the
    LLM and return CLAUDE.md's structured JSON profile as a plain dict.

    looking_for/offerings are passed in a second time, outside of merged_context,
    so this function can deterministically overwrite whatever the LLM produced
    for those two fields with the real verbatim values - the prompt instructs the
    LLM not to touch them, but per the confirmed architecture decision that these
    two fields must never be modified, that instruction alone isn't a strong
    enough guarantee.

    Retries once on any failure (invalid JSON, schema validation failure, or an
    ai_client API error) - a transient failure deserves the same one retry a bad
    response does. Raises ProfileNormalizationError if both attempts fail; this is
    not one of the optional enrichment sources, so a failure here must surface as
    a real per-participant enrichment failure rather than degrade silently.
    """
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = chat_json(SYSTEM_PROMPT, merged_context, max_tokens=MAX_RESPONSE_TOKENS)
            parsed = json.loads(raw)
            profile = StructuredProfile.model_validate(parsed)
        except Exception as e:
            last_error = e
            logger.warning(f"LLM normalization attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            continue

        result = profile.model_dump()
        result["person"]["looking_for"] = looking_for
        result["person"]["offerings"] = offerings
        return result

    raise ProfileNormalizationError(
        f"LLM normalization failed after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
