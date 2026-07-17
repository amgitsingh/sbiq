from __future__ import annotations


def strip_markdown_fence(raw: str) -> str:
    """Strip a ```json ... ``` (or plain ```...```) fence if present.

    Despite explicit "no markdown" instructions, the model occasionally wraps
    its JSON response in a code fence anyway - observed more often with
    web-search-enabled Responses API calls. json.loads() has no tolerance for
    this, so it must be stripped before parsing. Shared by every LLM call site
    that expects raw JSON back (llm_normalizer, llm_matcher).
    """
    text = raw.strip()
    if not text.startswith("```"):
        return text
    text = text.removeprefix("```json").removeprefix("```")
    text = text.removesuffix("```")
    return text.strip()
