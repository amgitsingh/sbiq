from __future__ import annotations

import json
import logging

from app.services.enrichment.cache import cache_get, cache_set
from app.services.enrichment.crunchbase_client import get_company_info
from app.services.enrichment.tavily_news_search import search_company_news
from app.services.enrichment.tavily_web_search import search_person_and_company
from app.services.enrichment.website_scraper import scrape_company_website

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 24 * 60 * 60
CACHE_KEY_PREFIX = "company_enrichment"


def normalize_company_name(company_name: str | None) -> str:
    return " ".join((company_name or "").strip().lower().split())


def get_company_enrichment(company_name: str | None, event_id: int, website_url: str | None) -> dict:
    """Run the 4 company-level enrichment sources (website, Tavily web, Tavily
    news, Crunchbase) for one company, cached in Redis by
    `normalized_company_name:event_id` with a 24-hour TTL. Multiple
    participants from the same company at the same event only trigger these
    external calls once.

    Person-level fields (name, designation, looking_for, offerings) are never
    part of this cache — callers must source those directly from the
    participant record and, separately, `linkedin_scraper.py`, per
    participant.

    Tavily web search is called with company name only (no person name) here:
    the result is cached and shared across every participant from this
    company, so binding it to one participant's name would leak that one
    person's search context into their colleagues' profiles — this also
    sidesteps the name-collision noise flagged in Task 13 (searching a
    person's name alone can surface an unrelated company entirely).

    Never raises — every underlying source already degrades to an empty
    value on failure, and a Redis outage degrades to "skip the cache," so
    this always returns a dict, worst case with all-empty values.
    """
    normalized = normalize_company_name(company_name)

    if not normalized:
        logger.info("No company name provided - running company enrichment uncached")
        return _run_sources(company_name, website_url)

    cache_key = f"{CACHE_KEY_PREFIX}:{event_id}:{normalized}"

    cached = cache_get(cache_key)
    if cached is not None:
        try:
            logger.info(f"Company enrichment cache hit for {cache_key!r}")
            return json.loads(cached)
        except json.JSONDecodeError:
            logger.warning(f"Corrupt company enrichment cache entry for {cache_key!r} - re-running")

    result = _run_sources(company_name, website_url)
    cache_set(cache_key, json.dumps(result), CACHE_TTL_SECONDS)
    return result


def _run_sources(company_name: str | None, website_url: str | None) -> dict:
    return {
        "website": scrape_company_website(website_url or ""),
        "tavily_web": search_person_and_company(None, company_name),
        "tavily_news": search_company_news(company_name),
        "crunchbase": get_company_info(company_name),
    }
