from __future__ import annotations

import logging

from app.services.ai_client import embed_text

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


class EmbeddingGenerationError(Exception):
    """Raised when embedding generation fails on every attempt."""


def serialize_profile_to_text(profile: dict) -> str:
    """Flatten a structured profile (Task 19's shape) into one text block for
    embedding - person fields first, then company fields, consistent field
    order every time so semantically identical profiles embed consistently.

    List fields are joined with ", "; missing/empty fields are omitted
    entirely rather than emitted as "None" or "" noise.
    """
    person = profile.get("person") or {}
    company = profile.get("company") or {}
    lines: list[str] = []

    def add(label: str, value) -> None:
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if value:
            lines.append(f"{label}: {value}")

    add("Name", person.get("name"))
    add("Designation", person.get("designation"))
    add("Looking for", person.get("looking_for"))
    add("Offerings", person.get("offerings"))

    add("Company", company.get("name"))
    add("Industry", company.get("industry"))
    add("Products", company.get("products"))
    add("Services", company.get("services"))
    add("Markets", company.get("markets"))
    add("Customers", company.get("customers"))
    add("Technologies", company.get("technologies"))
    add("Employee count", company.get("employee_count"))
    add("Headquarters", company.get("headquarters"))
    add("Funding stage", company.get("funding_stage"))
    add("Investors", company.get("investors"))
    add("Recent news", company.get("recent_news"))
    add("Summary", company.get("summary"))

    return "\n".join(lines)


def generate_embedding(profile: dict) -> tuple[list[float], int]:
    """Serialize a structured profile and embed it, retrying once on failure.

    Returns (vector, total_tokens). Raises EmbeddingGenerationError if both
    attempts fail - this is not an optional enrichment source, a failure here
    must surface as a real per-participant embedding failure.
    """
    text = serialize_profile_to_text(profile)
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            vector, total_tokens = embed_text(text)
            logger.info(f"Embedding generated: {total_tokens} tokens")
            return vector, total_tokens
        except Exception as e:
            last_error = e
            logger.warning(f"Embedding attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")

    raise EmbeddingGenerationError(
        f"Embedding generation failed after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
