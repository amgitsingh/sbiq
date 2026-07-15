from __future__ import annotations

import logging

from tavily import TavilyClient

from app.core.config import settings
from app.services.enrichment.source_toggle import toggleable

logger = logging.getLogger(__name__)

MAX_CHARS = 3_000
MAX_RESULTS = 5
# "Recent" news for a company is sparse day-to-day (funding/partnership news
# doesn't happen daily even for well-covered companies) - Tavily's own
# default of 3 days is too narrow and misses real hits a wider window finds.
NEWS_DAYS = 90


@toggleable("ENABLE_TAVILY_NEWS_SEARCH", empty_value=[])
def search_company_news(company_name: str | None) -> list[str]:
    """Tavily news-topic search for a company. Never raises — returns an
    empty list on missing config, API errors, quota exhaustion, or network
    failures, so one failed lookup never blocks the rest of the pipeline.
    """
    if not settings.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not configured - skipping Tavily news search")
        return []

    company_name = (company_name or "").strip()
    if not company_name:
        return []

    query = f"{company_name} news funding partnership product launch"

    try:
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(query=query, topic="news", days=NEWS_DAYS, max_results=MAX_RESULTS)
    except Exception as e:
        logger.warning(f"Tavily news search failed for query {query!r}: {e}")
        return []

    results = response.get("results") or []
    relevant = _filter_relevant(results, company_name)
    if not relevant:
        logger.info(f"No relevant Tavily news results for {company_name!r}")
        return []

    return _cap_snippets(relevant, MAX_CHARS)


def _filter_relevant(results: list[dict], company_name: str) -> list[str]:
    """Keep only snippets that actually mention the company.

    Tavily's news search frequently returns keyword-matched but
    company-irrelevant articles for smaller/less-covered companies
    (confirmed via live testing) - a generic query template like this one
    pulls in noise whenever no real company-specific news exists.
    """
    needle = company_name.lower()
    snippets = []
    for r in results:
        content = (r.get("content") or "").strip()
        title = (r.get("title") or "")
        if not content:
            continue
        if needle in content.lower() or needle in title.lower():
            snippets.append(content)
    return snippets


def _cap_snippets(snippets: list[str], limit: int) -> list[str]:
    capped: list[str] = []
    total = 0
    for s in snippets:
        remaining = limit - total
        if remaining <= 0:
            break
        if len(s) > remaining:
            capped.append(s[:remaining])
            break
        capped.append(s)
        total += len(s)
    return capped
