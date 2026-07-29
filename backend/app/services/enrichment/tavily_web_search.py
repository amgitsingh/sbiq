from __future__ import annotations

import logging

from tavily import TavilyClient

from app.core.config import settings
from app.services.enrichment.source_toggle import toggleable

logger = logging.getLogger(__name__)

MAX_CHARS = 4_000
RESULTS_PER_QUERY = 4

# Two differently-angled queries instead of one generic one - a single
# "{company} business" query was empirically thinner than a reference
# enrichment sample that clearly drew on several targeted searches per
# company (directory listings, partnership pages, not just top-5 snippets).
COMPANY_QUERY_TEMPLATES = [
    "{company} company overview products services",
    "{company} partnership OR membership OR client OR sponsor",
]

PERSON_MAX_CHARS = 2_000
PERSON_QUERY_TEMPLATE = "{person} {company}"

_EMPTY_RESULT = {"snippets": [], "sources": []}


@toggleable("ENABLE_TAVILY_WEB_SEARCH", empty_value=_EMPTY_RESULT)
def search_company(company_name: str | None) -> dict:
    """Tavily general web search on a company name only, for company-level
    enrichment context. Runs COMPANY_QUERY_TEMPLATES as separate queries and
    merges/dedupes the results - one generic query template consistently
    missed niche, specific sources (directory listings, partnership pages)
    that a second, differently-angled query surfaces.

    Deliberately company-only, no person name - this is the function
    company_enrichment.py calls and caches per-company; binding it to one
    person's name would leak that person's search context into colleagues'
    profiles who share the cached result. Use search_person() for
    person-specific search instead.

    Never raises - returns _EMPTY_RESULT on missing config, API errors, quota
    exhaustion, or network failures, so one failed lookup never blocks the
    rest of the enrichment pipeline.
    """
    if not settings.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not configured - skipping Tavily company search")
        return dict(_EMPTY_RESULT)

    company_name = (company_name or "").strip()
    if not company_name:
        return dict(_EMPTY_RESULT)

    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    snippets, sources = [], []
    seen_urls: set[str] = set()

    for template in COMPANY_QUERY_TEMPLATES:
        query = template.format(company=company_name)
        try:
            response = client.search(query=query, max_results=RESULTS_PER_QUERY)
        except Exception as e:
            logger.warning(f"Tavily company search failed for query {query!r}: {e}")
            continue

        for r in response.get("results") or []:
            content = (r.get("content") or "").strip()
            url = (r.get("url") or "").strip()
            if not content or (url and url in seen_urls):
                continue
            snippets.append(content)
            if url:
                sources.append(url)
                seen_urls.add(url)

    if not snippets:
        logger.info(f"No Tavily company search results for {company_name!r}")
        return dict(_EMPTY_RESULT)

    return {"snippets": _cap_snippets(snippets, MAX_CHARS), "sources": sources}


@toggleable("ENABLE_TAVILY_PERSON_SEARCH", empty_value=_EMPTY_RESULT)
def search_person(person_name: str | None, company_name: str | None) -> dict:
    """Tavily web search on a person + company name, for person-level
    enrichment context.

    Deliberately NOT routed through company_enrichment.py's Redis cache -
    unlike search_company, this is uncached and runs once per participant
    (cost scales with participant count, not company count), gated by its
    own toggle (ENABLE_TAVILY_PERSON_SEARCH) so it can be turned off
    independently if that cost profile is undesirable.

    Never raises - returns _EMPTY_RESULT on missing config, API errors, quota
    exhaustion, or network failures, so one failed lookup never blocks the
    rest of the enrichment pipeline.
    """
    if not settings.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not configured - skipping Tavily person search")
        return dict(_EMPTY_RESULT)

    person_name = (person_name or "").strip()
    company_name = (company_name or "").strip()
    if not person_name and not company_name:
        return dict(_EMPTY_RESULT)

    query = PERSON_QUERY_TEMPLATE.format(person=person_name, company=company_name).strip()

    try:
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(query=query, max_results=RESULTS_PER_QUERY)
    except Exception as e:
        logger.warning(f"Tavily person search failed for query {query!r}: {e}")
        return dict(_EMPTY_RESULT)

    snippets, sources = [], []
    for r in response.get("results") or []:
        content = (r.get("content") or "").strip()
        if not content:
            continue
        snippets.append(content)
        if url := (r.get("url") or "").strip():
            sources.append(url)

    if not snippets:
        logger.info(f"No Tavily person search results for query {query!r}")
        return dict(_EMPTY_RESULT)

    return {"snippets": _cap_snippets(snippets, PERSON_MAX_CHARS), "sources": sources}


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
