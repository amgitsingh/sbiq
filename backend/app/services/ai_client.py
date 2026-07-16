from __future__ import annotations

from openai import OpenAI

from app.core.config import settings

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Lazily construct the shared LLM client.

    Model-agnostic per CLAUDE.md: works against any OpenAI-compatible
    endpoint (OpenAI, or an Anthropic/Mistral-compatible proxy) purely via
    AI_BASE_URL/AI_API_KEY - switching providers is a config change only.
    """
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.AI_API_KEY, base_url=settings.AI_BASE_URL)
    return _client


def chat_json(system_prompt: str, user_prompt: str, *, max_tokens: int) -> str:
    """Call the configured LLM in JSON mode, return the raw JSON text.

    Raises on any API-level failure (auth, rate limit, network, missing
    config) - unlike enrichment sources, callers of this function are not
    optional pipeline steps, so a failure here must propagate to the caller
    rather than degrade silently.
    """
    client = get_client()
    response = client.chat.completions.create(
        model=settings.AI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or "{}"


def chat_json_web_search(system_prompt: str, user_prompt: str, *, max_tokens: int) -> str:
    """Like chat_json, but lets the model autonomously search the web via
    OpenAI's Responses API hosted `web_search` tool - one call does both the
    search (OpenAI runs it, not us) and the final synthesis.

    OpenAI-specific - unlike chat_json, this is not portable to a generic
    OpenAI-compatible endpoint. Callers should gate this behind
    settings.ENABLE_LLM_WEB_SEARCH so a non-OpenAI AI_BASE_URL can fall back
    to chat_json instead.

    No server-enforced JSON mode here (uncertain this composes cleanly with
    the web_search tool) - relies on the prompt instructing JSON-only output,
    same as the caller's existing json.loads + schema validation + retry-once
    safety net.

    Raises on any API-level failure, same as chat_json.
    """
    client = get_client()
    response = client.responses.create(
        model=settings.AI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=[{"type": "web_search"}],
        max_output_tokens=max_tokens,
    )
    return response.output_text or "{}"
