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

# Two differently-angled queries instead of one - the funding/partnership
# template alone misses smaller companies' press releases and award/
# recognition news that a second query template surfaces.
NEWS_QUERY_TEMPLATES = [
    "{company} news funding partnership product launch",
    "{company} press release announcement award",
]

_EMPTY_RESULT = {"snippets": [], "sources": []}


@toggleable("ENABLE_TAVILY_NEWS_SEARCH", empty_value=_EMPTY_RESULT)
def search_company_news(company_name: str | None) -> dict:
    """Tavily news-topic search for a company, across NEWS_QUERY_TEMPLATES,
    merged and deduped by URL. Never raises — returns _EMPTY_RESULT on
    missing config, API errors, quota exhaustion, or network failures, so
    one failed lookup never blocks the rest of the pipeline.
    """
    if not settings.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not configured - skipping Tavily news search")
        return dict(_EMPTY_RESULT)

    company_name = (company_name or "").strip()
    if not company_name:
        return dict(_EMPTY_RESULT)

    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    snippets, sources = [], []
    seen_urls: set[str] = set()

    for template in NEWS_QUERY_TEMPLATES:
        query = template.format(company=company_name)
        try:
            response = client.search(query=query, topic="news", days=NEWS_DAYS, max_results=MAX_RESULTS)
        except Exception as e:
            logger.warning(f"Tavily news search failed for query {query!r}: {e}")
            continue

        for content, url in _filter_relevant(response.get("results") or [], company_name):
            if url and url in seen_urls:
                continue
            snippets.append(content)
            if url:
                sources.append(url)
                seen_urls.add(url)

    if not snippets:
        logger.info(f"No relevant Tavily news results for {company_name!r}")
        return dict(_EMPTY_RESULT)

    return {"snippets": _cap_snippets(snippets, MAX_CHARS), "sources": sources}


def _filter_relevant(results: list[dict], company_name: str) -> list[tuple[str, str]]:
    """Keep only (content, url) pairs that actually mention the company.

    Tavily's news search frequently returns keyword-matched but
    company-irrelevant articles for smaller/less-covered companies
    (confirmed via live testing) - a generic query template like this one
    pulls in noise whenever no real company-specific news exists.
    """
    needle = company_name.lower()
    pairs = []
    for r in results:
        content = (r.get("content") or "").strip()
        title = (r.get("title") or "")
        url = (r.get("url") or "").strip()
        if not content:
            continue
        if needle in content.lower() or needle in title.lower():
            pairs.append((content, url))
    return pairs


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
