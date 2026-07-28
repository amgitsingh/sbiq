from __future__ import annotations

import json
import logging

from app.core.config import settings
from app.services.ai_client import chat_json, chat_json_web_search
from app.services.enrichment.profile_schema import StructuredProfile
from app.services.json_utils import strip_markdown_fence

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
  },
  "ecosystem_role": string or null
}

"ecosystem_role" classifies what role this participant plays in the business \
ecosystem - their access, influence, capital, deal flow, or network reach - \
NOT what industry they're in or what they sell. Two participants in unrelated \
industries can be an excellent match if their roles are complementary (e.g. a \
company seeking capital paired with an investor), while two participants in \
the same industry with the same role are often a weak match (e.g. two direct \
sellers competing for the same buyers). Pick exactly one of these 11 \
categories, or null if none genuinely fit:
- Direct Buyer: actively purchasing goods/services matching what others offer.
- Direct Seller: offers goods/services that others are actively buying.
- Network Multiplier: has broad reach/influence across many other participants \
(e.g. runs a mastermind group, advises many CEOs, organizes recurring events).
- Ecosystem Builder: creates or grows a business community/platform that \
others plug into.
- Investor: provides capital (equity, debt, or otherwise) to other participants.
- Deal Flow Source: surfaces investable or fundable opportunities to investors.
- Strategic Connector: bridges two otherwise-unconnected parts of the ecosystem \
(e.g. cross-border, cross-industry, cross-community introductions).
- Market Access Partner: provides access to a specific customer segment, \
market, or channel others want to reach.
- Community Leader: leads or represents an identifiable group/community whose \
trust or attention is valuable.
- Specialist Advisor: provides expert advisory services (legal, financial, \
technical) that a broad range of other participants need.
- Corporate Entry Point: an individual contact inside a large corporate/
enterprise who can open doors to that organization.

Rules:
- Fill every field you can reasonably support from the given context. Use null or an \
empty list for anything not mentioned anywhere - never invent facts.
- If the given context is too thin to fill in important company fields (industry, \
products, services, summary, etc.), and you have web search available, search the \
web for the company (and person, if that helps) to fill the gaps. Prefer the given \
context over search results whenever they overlap or conflict.
- "company.summary" should be a short synthesis of everything known about the \
company, in your own words.
- Prefer the participant's own Excel-submitted values for "person.name", \
"person.designation", and "company.name" over any conflicting value from \
LinkedIn, web search, or elsewhere.
- Copy "person.looking_for" and "person.offerings" through EXACTLY as given in the \
participant's Excel section, character for character, with no rewording, \
summarizing, or translation. Do not use other sections to fill these two fields in \
if the Excel section leaves them blank - leave them null instead.
- The top-level "ecosystem_role" key is REQUIRED in every response - never omit it. \
Actively attempt the classification using the person's designation, the company's \
industry/products/services/summary, and what they're looking for/offering - almost \
every participant fits one of the 11 categories once you consider what access, \
capital, influence, or reach they bring. Only use null if you have genuinely \
considered all 11 categories against the available context and none apply.
- Respond with a single JSON object only, matching the shape above exactly, with \
"person", "company", AND "ecosystem_role" all present as top-level keys. No \
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
            if settings.ENABLE_LLM_WEB_SEARCH:
                raw = chat_json_web_search(SYSTEM_PROMPT, merged_context, max_tokens=MAX_RESPONSE_TOKENS)
            else:
                raw = chat_json(SYSTEM_PROMPT, merged_context, max_tokens=MAX_RESPONSE_TOKENS)
            parsed = json.loads(strip_markdown_fence(raw))
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
