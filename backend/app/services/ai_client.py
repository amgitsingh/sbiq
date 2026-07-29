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


def chat_json_with_usage(system_prompt: str, user_prompt: str, *, max_tokens: int) -> tuple[str, dict]:
    """Like chat_json, but also returns token usage - for call sites that need
    to log input/output token counts (e.g. llm_matcher), without changing
    chat_json's simpler contract for callers that don't.
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
    usage = response.usage
    token_usage = {
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
    }
    return response.choices[0].message.content or "{}", token_usage


def chat_json_web_search(
    system_prompt: str, user_prompt: str, *, max_tokens: int, force_tool_use: bool = False
) -> str:
    """Like chat_json, but lets the model autonomously search the web via
    OpenAI's Responses API hosted `web_search` tool - one call does both the
    search (OpenAI runs it, not us) and the final synthesis.

    OpenAI-specific - unlike chat_json, this is not portable to a generic
    OpenAI-compatible endpoint. Callers should gate this behind
    settings.ENABLE_LLM_WEB_SEARCH so a non-OpenAI AI_BASE_URL can fall back
    to chat_json instead.

    force_tool_use=True passes tool_choice="required", forcing at least one
    tool call - unambiguous here since `web_search` is the only tool in the
    array. Without it, the model may skip searching entirely even when the
    prompt asks it to (observed: prompt-only instructions were too easy to
    skip whenever the merged context already looked superficially complete).
    Defaults to False so existing callers are unaffected.

    No server-enforced JSON mode here (uncertain this composes cleanly with
    the web_search tool) - relies on the prompt instructing JSON-only output,
    same as the caller's existing json.loads + schema validation + retry-once
    safety net.

    Raises on any API-level failure, same as chat_json.
    """
    client = get_client()
    kwargs: dict = {}
    if force_tool_use:
        kwargs["tool_choice"] = "required"
    response = client.responses.create(
        model=settings.AI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=[{"type": "web_search"}],
        max_output_tokens=max_tokens,
        **kwargs,
    )
    return response.output_text or "{}"


def embed_text(text: str) -> tuple[list[float], int]:
    """Call the configured embedding model, return (vector, total_tokens).

    Thin wrapper, same contract as chat_json - raises on any API-level
    failure rather than degrading silently. Retry policy lives with the
    caller (app.services.embedding), same split as llm_normalizer owning
    the retry loop around chat_json/chat_json_web_search.
    """
    client = get_client()
    response = client.embeddings.create(model=settings.AI_EMBEDDING_MODEL, input=text)
    return list(response.data[0].embedding), response.usage.total_tokens
