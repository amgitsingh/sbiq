from __future__ import annotations

import logging

from tavily import TavilyClient

from app.core.config import settings
from app.services.enrichment.source_toggle import toggleable

logger = logging.getLogger(__name__)

MAX_CHARS = 3_000
MAX_RESULTS = 5


@toggleable("ENABLE_TAVILY_WEB_SEARCH", empty_value=None)
def search_person_and_company(person_name: str | None, company_name: str | None) -> str | None:
    """Tavily general web search on a person + company name, for enrichment context.

    Never raises — returns None on missing config, API errors, quota
    exhaustion, or network failures, so one failed lookup never blocks the
    rest of the enrichment pipeline.
    """
    if not settings.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not configured - skipping Tavily web search")
        return None

    person_name = (person_name or "").strip()
    company_name = (company_name or "").strip()
    if not person_name and not company_name:
        return None

    query = f"{person_name} {company_name} business".strip()

    try:
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(query=query, max_results=MAX_RESULTS)
    except Exception as e:
        logger.warning(f"Tavily web search failed for query {query!r}: {e}")
        return None

    results = response.get("results") or []
    snippets = [r.get("content", "").strip() for r in results if r.get("content")]
    if not snippets:
        logger.info(f"No Tavily results for query {query!r}")
        return None

    return " ".join(snippets)[:MAX_CHARS]
