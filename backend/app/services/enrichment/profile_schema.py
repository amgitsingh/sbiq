from __future__ import annotations

from pydantic import BaseModel


class PersonProfile(BaseModel):
    name: str | None = None
    designation: str | None = None
    looking_for: str | None = None
    offerings: str | None = None


class CompanyProfile(BaseModel):
    name: str | None = None
    website: str | None = None
    industry: str | None = None
    products: list[str] = []
    services: list[str] = []
    markets: list[str] = []
    customers: list[str] = []
    technologies: list[str] = []
    employee_count: str | None = None
    headquarters: str | None = None
    funding_stage: str | None = None
    investors: list[str] = []
    recent_news: list[str] = []
    summary: str | None = None


class StructuredProfile(BaseModel):
    person: PersonProfile
    company: CompanyProfile
    # Which role this participant plays in the business ecosystem (access,
    # influence, capital, deal flow, network reach) - not what they sell.
    # One of app.services.matching.ecosystem_role.ECOSYSTEM_ROLES, or None if
    # the LLM couldn't confidently classify it. See
    # docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md, Item 2.
    ecosystem_role: str | None = None
    # Real URLs the enrichment pipeline actually fetched data from (Tavily
    # company/person/news search results), deterministically collected in
    # enrichment_tasks.py and stamped in by llm_normalizer.
    # normalize_participant_profile's source_urls param - never asked of or
    # produced by the LLM itself, to avoid hallucinated citations.
    research_sources: list[str] = []
