import difflib
import logging
import re

logger = logging.getLogger(__name__)

# Canonical field keys a header can map to. Note "name" is split into
# first_name/last_name for sources that export them separately (e.g. the real
# MeerBusiness Amsterdam export) — resolve_name() reconciles both shapes.
CANONICAL_HEADERS: dict[str, list[str]] = {
    "name": ["name", "full name", "naam", "volledige naam"],
    "first_name": ["first name", "firstname", "voornaam"],
    "last_name": ["last name", "lastname", "surname", "achternaam"],
    "email": ["email", "e-mail", "email address", "e-mail address", "e-mailadres", "emailadres"],
    "phone": [
        "phone", "phone number", "mobile phone", "mobile", "telephone",
        "telefoonnummer", "telefoon", "mobiel",
    ],
    "company": [
        "company", "company name", "organisation", "organization",
        "bedrijfsnaam", "bedrijf", "organisatie",
    ],
    "designation": ["job title", "title", "position", "designation", "functie", "rol"],
    "sector": ["sector", "which sector are you in?", "industry", "branche"],
    "company_size": [
        "company size", "organization size", "fte", "number of employees",
        "how large is your organization in ftes?", "aantal medewerkers", "grootte organisatie",
    ],
    "membership_tier": [
        "membership", "membership tier", "member", "member type",
        "are you a member of meerbusiness amsterdam?", "lidmaatschap", "lid",
    ],
    "looking_for": [
        "looking for", "what are you looking for", "what are you looking for right now?",
        "op zoek naar", "waar ben je naar op zoek",
    ],
    "offerings": ["offer", "offering", "offerings", "what do you offer?", "aanbod", "wat bied je aan"],
    "ideal_connection": [
        "ideal connection", "who would you like to connect with",
        "who would you ideally like to connect with?", "wie wil je graag ontmoeten",
    ],
    "biggest_opportunity": [
        "biggest opportunity", "opportunity",
        "what is the biggest opportunity in the next 3 months?", "grootste kans",
    ],
    "website": ["website", "company website", "site", "url", "webadres"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin profile", "linkedin-profiel", "linkedin profiel"],
}

FUZZY_MATCH_CUTOFF = 0.82


def _normalize(header: str | None) -> str:
    if not header:
        return ""
    h = header.strip().lower()
    h = re.sub(r"[^\w\s]", " ", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h


def _build_lookup() -> tuple[dict[str, str], list[str]]:
    lookup: dict[str, str] = {}
    for canonical_key, variants in CANONICAL_HEADERS.items():
        for variant in variants:
            normalized = _normalize(variant)
            lookup.setdefault(normalized, canonical_key)
    return lookup, list(lookup.keys())


_NORMALIZED_LOOKUP, _NORMALIZED_VARIANTS = _build_lookup()


def _match_header(header: str) -> str | None:
    normalized = _normalize(header)
    if not normalized:
        return None

    if normalized in _NORMALIZED_LOOKUP:
        return _NORMALIZED_LOOKUP[normalized]

    close = difflib.get_close_matches(normalized, _NORMALIZED_VARIANTS, n=1, cutoff=FUZZY_MATCH_CUTOFF)
    if close:
        return _NORMALIZED_LOOKUP[close[0]]

    return None


def map_headers(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map raw column headers to canonical field keys.

    Returns (header_to_field, unmapped_headers). Unmapped headers are warnings,
    not errors — the caller decides whether to proceed anyway.
    """
    mapping: dict[str, str] = {}
    unmapped: list[str] = []

    for header in headers:
        if not header:
            continue
        canonical_key = _match_header(header)
        if canonical_key:
            mapping[header] = canonical_key
        else:
            unmapped.append(header)

    return mapping, unmapped


def map_row(row: dict, header_map: dict[str, str]) -> dict:
    """Rekey a raw row dict (original header -> value) to (canonical field -> value).

    Keys prefixed with '__' are pipeline metadata (e.g. '__row_number'), not
    spreadsheet columns, and pass through unchanged.
    """
    mapped: dict = {}

    for original_header, value in row.items():
        if original_header.startswith("__"):
            mapped[original_header] = value
            continue

        canonical_key = header_map.get(original_header)
        if not canonical_key:
            continue
        if canonical_key in mapped and mapped[canonical_key] not in (None, ""):
            logger.warning(
                f"Multiple headers map to '{canonical_key}'; keeping first non-empty value, "
                f"ignoring '{original_header}'"
            )
            continue
        mapped[canonical_key] = value

    return mapped


def resolve_name(mapped_row: dict) -> str | None:
    """Reconcile a single 'name' field vs. split first_name/last_name into one string."""
    if mapped_row.get("name"):
        return str(mapped_row["name"]).strip()

    first = str(mapped_row.get("first_name") or "").strip()
    last = str(mapped_row.get("last_name") or "").strip()
    full = f"{first} {last}".strip()
    return full or None
