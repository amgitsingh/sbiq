from __future__ import annotations

import re
from collections import defaultdict

# Keyword-based sector classifier. Real submitted `sector` text is free-form,
# not a controlled vocabulary (confirmed against real sample data - e.g.
# "Banking / occupational health and absenteeism", "cultural, creative and
# organizational development sector") and is often multi-topic, so a raw string
# can and does classify into more than one category. Categories chosen to cover
# both the real sample data's sectors and common general B2B ones.
#
# Bilingual (English + Dutch) in the same list per category, no separate
# language-detection step needed - classify_sector() just does substring
# matching against whatever's here, same convention already proven in
# decision_authority.SENIOR_TITLE_KEYWORDS. Dutch terms added where the
# English keyword doesn't already happen to be a substring of the Dutch word
# (e.g. "transport" is identical in both languages - no Dutch entry needed;
# "energy" is not a substring of "energie" - Dutch entry added).
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "finance_banking": [
        "bank", "financ", "pension", "insuran", "invest", "private debt", "fintech",
        "bankwezen", "verzeker", "pensioen",
    ],
    "real_estate": ["real estate", "property", "realty", "vastgoed", "onroerend goed"],
    "health_wellness": ["health", "wellness", "fitness", "medical", "care", "gezondheid", "zorg", "welzijn"],
    "hospitality_tourism": ["tourism", "hospitality", "hotel", "travel", "event", "toerisme", "horeca"],
    "culture_entertainment": [
        "cultur", "entertainment", "art", "creative", "music", "film", "cultuur", "amusement", "creatie",
    ],
    "media_photography": [
        "media", "photograph", "marketing", "advertis", "communicat", "fotografie", "adverten",
    ],
    "education_training": [
        "education", "training", "language", "coach", "school", "academy",
        "onderwijs", "opleiding", "academie", "taal",
    ],
    "administrative_hr": [
        "administrat", "office management", "personal assistant", " hr ", "human resources", "recruit",
        "administratie", "personeelszaken", "werving",
    ],
    "technology": ["tech", "software", " it ", "saas", "digital", "data", "digitaal"],
    "retail_ecommerce": ["retail", "ecommerce", "e-commerce", "shop", "consumer goods", "detailhandel", "webshop"],
    "manufacturing": ["manufactur", "industrial", "production", "factory", "productie", "fabriek"],
    "consulting": ["consult", "advisory", "strategy", "advies", "strategie"],
    "legal": ["legal", "law", "attorney", "notary", "juridisch", "advocaat", "notaris"],
    "logistics": ["logistic", "supply chain", "transport", "freight", "shipping", "logistiek"],
    "construction": ["construction", "building", "architect", "engineering", "bouw"],
    "agriculture_food": ["agricultur", "farm", "food", "beverage", "landbouw", "voedsel", "boerderij"],
    "energy": ["energy", "sustainab", "renewable", "solar", "utilit", "energie", "duurzaam"],
    "nonprofit_government": [
        "nonprofit", "non-profit", "government", "public sector", "ngo", "charity", "overheid", "goede doel",
    ],
    "telecommunications": ["telecom"],
}

# Symmetric pairs - built into a bidirectional lookup below so adjacency can't
# drift out of sync (e.g. A lists B but B forgets to list A).
_ADJACENT_PAIRS: list[tuple[str, str]] = [
    ("finance_banking", "real_estate"),
    ("finance_banking", "legal"),
    ("finance_banking", "consulting"),
    ("finance_banking", "technology"),
    ("real_estate", "construction"),
    ("health_wellness", "hospitality_tourism"),
    ("health_wellness", "agriculture_food"),
    ("hospitality_tourism", "culture_entertainment"),
    ("hospitality_tourism", "agriculture_food"),
    ("culture_entertainment", "media_photography"),
    ("culture_entertainment", "education_training"),
    ("media_photography", "technology"),
    ("education_training", "consulting"),
    ("education_training", "nonprofit_government"),
    ("administrative_hr", "consulting"),
    ("administrative_hr", "legal"),
    ("technology", "telecommunications"),
    ("technology", "consulting"),
    ("retail_ecommerce", "manufacturing"),
    ("retail_ecommerce", "logistics"),
    ("retail_ecommerce", "technology"),
    ("manufacturing", "logistics"),
    ("manufacturing", "construction"),
    ("manufacturing", "energy"),
    ("consulting", "legal"),
    ("construction", "energy"),
]

SECTOR_ADJACENCY: dict[str, set[str]] = defaultdict(set)
for _a, _b in _ADJACENT_PAIRS:
    SECTOR_ADJACENCY[_a].add(_b)
    SECTOR_ADJACENCY[_b].add(_a)


def classify_sector(raw: str | None) -> set[str]:
    """Map free-text sector into zero or more canonical categories via
    substring keyword matching. Zero categories means unclassifiable (blank,
    or text that matches none of the known keyword groups) - callers treat
    that the same as "unrelated", not as an error.
    """
    if not raw:
        return set()
    text = f" {raw.strip().lower()} "
    return {category for category, keywords in SECTOR_KEYWORDS.items() if any(kw in text for kw in keywords)}


def sector_alignment_score(a_sector: str | None, b_sector: str | None) -> float:
    """1.0 if any classified category matches exactly, 0.5 if any pair of
    categories is adjacent, else 0.0 (including when either side is
    unclassifiable - no data means no confidence, not a free pass).
    """
    a_categories = classify_sector(a_sector)
    b_categories = classify_sector(b_sector)
    if not a_categories or not b_categories:
        return 0.0

    if a_categories & b_categories:
        return 1.0

    for category in a_categories:
        if SECTOR_ADJACENCY[category] & b_categories:
            return 0.5

    return 0.0


# (low, high) employee-count bounds, inclusive, in bucket order.
SIZE_BUCKETS: list[tuple[float, float]] = [
    (1, 10),
    (11, 50),
    (51, 200),
    (201, 1000),
    (1000, float("inf")),
]

# Matches integers, with optional thousands commas and a decimal part -
# "1,000", "22,000", "1.5" all match. Deliberately doesn't match a trailing
# "+" (handled implicitly - "4400 +" still yields the number "4400").
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")


def _extract_numbers(raw: str) -> list[float]:
    return [float(match.replace(",", "")) for match in _NUMBER_RE.findall(raw)]


def _parse_employee_count(raw: str | None) -> float | None:
    """Best-effort numeric employee count from free text.

    Real submitted values (confirmed against sample data) include bare
    numbers ("50"), "FTE"-suffixed numbers ("25 FTE"), ranges ("10-20", "1 -
    10 FTE"), "+"-suffixed numbers ("4400 +"), comma thousands ("55,000"),
    decimals ("1.5"), and outright garbage ("x", "N/A", "I am bringing a
    guest", "ghhh"). A range is averaged; garbage with no digits at all
    returns None (unclassifiable, not zero).
    """
    if not raw:
        return None
    numbers = _extract_numbers(raw)
    if not numbers:
        return None
    if len(numbers) == 1:
        return numbers[0]
    return (numbers[0] + numbers[1]) / 2


def _bucket_index(count: float) -> int | None:
    if count < 0:
        return None
    count = max(count, 1)  # a literal "0" is treated as "just me" (bucket 0)
    for i, (lo, hi) in enumerate(SIZE_BUCKETS):
        if lo <= count <= hi:
            return i
    return None


def company_size_score(a_company_size: str | None, b_company_size: str | None) -> float:
    """1.0 same bucket, 0.5 one bucket apart, 0.0 two+ apart or unparseable."""
    a_count = _parse_employee_count(a_company_size)
    b_count = _parse_employee_count(b_company_size)
    if a_count is None or b_count is None:
        return 0.0

    a_bucket = _bucket_index(a_count)
    b_bucket = _bucket_index(b_count)
    if a_bucket is None or b_bucket is None:
        return 0.0

    diff = abs(a_bucket - b_bucket)
    if diff == 0:
        return 1.0
    if diff == 1:
        return 0.5
    return 0.0
