from __future__ import annotations

import json
import logging

from app.services.ai_client import chat_json
from app.services.json_utils import strip_markdown_fence

logger = logging.getLogger(__name__)

MAX_RESPONSE_TOKENS_TEXT = 1_000
MAX_RESPONSE_TOKENS_MATCH = 2_000
MAX_ATTEMPTS = 2

# Same convention as llm_normalizer.LANGUAGE_NAMES/llm_matcher.LANGUAGE_NAMES,
# but bidirectional here - on-demand translation can go either en->nl or
# nl->en depending on what the caller's stored content vs. requested lang is.
LANGUAGE_NAMES = {"en": "English", "nl": "Dutch"}

_TEXT_SYSTEM_PROMPT = """You are a professional translator for a business \
matchmaking platform. Translate the given text into {language}, preserving \
tone, meaning, and any names/companies exactly as written (do not translate \
proper nouns). Respond with a single JSON object of exactly this shape: \
{{"translation": <string>}}. No markdown, no commentary."""

_MATCH_SYSTEM_PROMPT = """You are a professional translator for a business \
matchmaking platform. You will be given a JSON object with "reasoning" (a \
list of short strings), "email_draft" (a string or null), and \
"linkedin_draft" (a string or null). Translate every non-null string value \
into {language}, preserving tone, meaning, and any names/companies exactly \
as written (do not translate proper nouns). Preserve nulls as null - do not \
invent content for a null field. Respond with a single JSON object of \
exactly the same shape: {{"reasoning": [<string>, ...], "email_draft": \
<string or null>, "linkedin_draft": <string or null>}}. No markdown, no \
commentary."""


class TranslationError(Exception):
    """Raised when the LLM never produced a valid translation after retrying."""


def _language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def translate_text(text: str, target_language: str) -> str:
    """Translate one plain-text field (e.g. company.summary) into
    target_language ("en"/"nl"). Retries once on any failure - invalid JSON,
    missing key, or an ai_client API error. Raises TranslationError if both
    attempts fail.
    """
    system_prompt = _TEXT_SYSTEM_PROMPT.format(language=_language_name(target_language))

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = chat_json(system_prompt, text, max_tokens=MAX_RESPONSE_TOKENS_TEXT)
            parsed = json.loads(strip_markdown_fence(raw))
            translation = parsed["translation"]
            if not isinstance(translation, str):
                raise ValueError(f"Expected a string 'translation', got {type(translation)}")
            return translation
        except Exception as e:
            last_error = e
            logger.warning(f"translate_text attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")

    raise TranslationError(f"translate_text failed after {MAX_ATTEMPTS} attempts: {last_error}") from last_error


def translate_match_content(
    *,
    reasoning: list[str],
    email_draft: str | None,
    linkedin_draft: str | None,
    target_language: str,
) -> dict:
    """Translate a match's reasoning/email_draft/linkedin_draft into
    target_language in one LLM call (cheaper than three separate calls, same
    "bundle fields into one call" convention llm_normalizer's
    WEB_SEARCH_ADDENDUM already uses).

    email_draft/linkedin_draft may be None (the bidirectional-mirror-row
    case, which never has real drafts) - the prompt is instructed to
    preserve nulls, not invent content for them; also enforced here
    afterward, so a model slip can't turn a null into fabricated text.

    Retries once on any failure. Raises TranslationError if both attempts fail.
    """
    system_prompt = _MATCH_SYSTEM_PROMPT.format(language=_language_name(target_language))
    user_prompt = json.dumps(
        {"reasoning": reasoning, "email_draft": email_draft, "linkedin_draft": linkedin_draft}
    )

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = chat_json(system_prompt, user_prompt, max_tokens=MAX_RESPONSE_TOKENS_MATCH)
            parsed = json.loads(strip_markdown_fence(raw))
            translated_reasoning = parsed["reasoning"]
            if not isinstance(translated_reasoning, list) or len(translated_reasoning) != len(reasoning):
                raise ValueError(
                    f"Expected {len(reasoning)} reasoning bullets back, got {parsed.get('reasoning')!r}"
                )
            return {
                "reasoning": translated_reasoning,
                # Enforced regardless of what the model returned - a null
                # input field must stay null, never fabricated.
                "email_draft": parsed.get("email_draft") if email_draft is not None else None,
                "linkedin_draft": parsed.get("linkedin_draft") if linkedin_draft is not None else None,
            }
        except Exception as e:
            last_error = e
            logger.warning(f"translate_match_content attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")

    raise TranslationError(
        f"translate_match_content failed after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
