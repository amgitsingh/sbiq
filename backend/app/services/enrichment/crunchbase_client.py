from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.services.enrichment.source_toggle import toggleable

logger = logging.getLogger(__name__)

BASE_URL = "https://api.crunchbase.com/api/v4"
TIMEOUT_SECONDS = 10.0

# Fields requested from Crunchbase's v4 "searches/organizations" endpoint.
# NOTE: these field_ids reflect Crunchbase's documented v4 REST API shape at
# implementation time. This client has NOT been exercised against a live
# account — CRUNCHBASE_API_KEY is unset and ENABLE_CRUNCHBASE defaults to
# False (see docs/PLAN.md Task 15: no API key available yet). Before flipping
# ENABLE_CRUNCHBASE on, verify these field_ids and the response shape
# against Crunchbase's current API reference — their schema has changed
# over time and this may need adjustment.
FIELD_IDS = [
    "identifier",
    "short_description",
    "num_employees_enum",
    "founded_on",
    "headquarters_regions",
    "funding_stage",
    "funding_total",
    "last_funding_type",
    "investor_identifiers",
    "category_groups",
]


@toggleable("ENABLE_CRUNCHBASE", empty_value={})
def get_company_info(company_name: str | None) -> dict:
    """Query Crunchbase for structured company data: employee count,
    headquarters, funding stage, funding total, investors, founding year,
    categories. Never raises — returns a partial (possibly empty) dict on
    any failure (company not found, rate limit, network error, missing
    config) so one lookup never blocks the rest of the pipeline.
    """
    if not settings.CRUNCHBASE_API_KEY:
        logger.warning("CRUNCHBASE_API_KEY not configured - skipping Crunchbase lookup")
        return {}

    company_name = (company_name or "").strip()
    if not company_name:
        return {}

    payload = {
        "field_ids": FIELD_IDS,
        "query": [
            {
                "type": "predicate",
                "field_id": "identifier",
                "operator_id": "contains",
                "values": [company_name],
            }
        ],
        "limit": 1,
    }

    try:
        response = httpx.post(
            f"{BASE_URL}/searches/organizations",
            json=payload,
            headers={"X-cb-user-key": settings.CRUNCHBASE_API_KEY},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.RequestError as e:
        logger.warning(f"Crunchbase request failed for {company_name!r}: {e}")
        return {}

    if response.status_code == 404:
        logger.info(f"Crunchbase: company not found: {company_name!r}")
        return {}
    if response.status_code == 429:
        logger.warning(f"Crunchbase rate limit hit for {company_name!r}")
        return {}
    if response.status_code != 200:
        logger.warning(f"Crunchbase returned HTTP {response.status_code} for {company_name!r}")
        return {}

    try:
        data = response.json()
    except ValueError:
        logger.warning(f"Crunchbase returned invalid JSON for {company_name!r}")
        return {}

    entities = data.get("entities") or []
    if not entities:
        logger.info(f"Crunchbase: no results for {company_name!r}")
        return {}

    return _map_entity(entities[0])


def _map_entity(entity: dict) -> dict:
    props = entity.get("properties") or {}
    result: dict = {}

    if employee_range := props.get("num_employees_enum"):
        result["employee_count"] = employee_range

    if founded := props.get("founded_on"):
        value = (founded or {}).get("value") or ""
        result["founding_year"] = value[:4] or None

    if hq := props.get("headquarters_regions"):
        result["headquarters"] = [r.get("value") for r in hq if r.get("value")]

    if funding_stage := props.get("funding_stage"):
        result["funding_stage"] = funding_stage

    if funding_total := props.get("funding_total"):
        result["funding_total"] = funding_total.get("value_usd") or funding_total.get("value")

    if investors := props.get("investor_identifiers"):
        result["investors"] = [i.get("value") for i in investors if i.get("value")]

    if categories := props.get("category_groups"):
        result["categories"] = [c.get("value") for c in categories if c.get("value")]

    return {k: v for k, v in result.items() if v not in (None, [], "")}
