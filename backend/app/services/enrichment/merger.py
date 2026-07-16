from __future__ import annotations

from typing import Any


def build_enrichment_context(
    *,
    name: str | None,
    company: str | None,
    designation: str | None,
    looking_for: str | None,
    offerings: str | None,
    ideal_connection: str | None = None,
    biggest_opportunity: str | None = None,
    company_enrichment: dict[str, Any],
    linkedin_profile: dict[str, str] | None,
) -> str:
    """Combine one participant's Excel fields + all 5 enrichment sources into
    a single labeled text block - the input to Task 19's LLM normalization.

    Sections with no data are omitted entirely rather than left in as a
    "no data" placeholder: an absent section already reads as "unknown" to
    the LLM, and skipping it keeps prompt size (and cost, per
    AI_MAX_TOKENS_PER_RUN) down - real participant data is sparse enough that
    most sources return nothing for most people.

    looking_for/offerings appear here strictly as merge input, not as an
    instruction - Task 19's prompt is what must enforce copying them through
    unmodified into the final profile, per CLAUDE.md's verbatim rule.

    ideal_connection/biggest_opportunity aren't in Task 18's original source
    list (CLAUDE.md predates the Task 3 schema refinement that added these
    columns), but they're real free-text signal from the same Excel row with
    no other consumer, so they're included here as extra participant context
    for the LLM to draw on - same non-verbatim treatment as every enrichment
    section, never a field Task 19 must preserve exactly.

    company is stated explicitly here as a labeled Excel fact, not left for
    the LLM to infer from prose - live testing surfaced a real failure mode
    without it: for a participant with no "Company: ..." line, the LLM
    misread the "=== TAVILY ===" section header itself as the company name.
    """
    sections = [
        _participant_section(
            name,
            company,
            designation,
            looking_for,
            offerings,
            ideal_connection,
            biggest_opportunity,
        )
    ]

    if website := company_enrichment.get("website"):
        sections.append(f"=== WEBSITE ===\n{website}")

    if tavily_web := company_enrichment.get("tavily_web"):
        sections.append(f"=== TAVILY ===\n{tavily_web}")

    if tavily_news := company_enrichment.get("tavily_news"):
        news_text = "\n".join(f"- {snippet}" for snippet in tavily_news)
        sections.append(f"=== NEWS ===\n{news_text}")

    if crunchbase := company_enrichment.get("crunchbase"):
        sections.append(f"=== CRUNCHBASE ===\n{_format_dict(crunchbase)}")

    if linkedin_profile:
        sections.append(f"=== LINKEDIN ===\n{_format_linkedin(linkedin_profile)}")

    return "\n\n".join(sections)


def _participant_section(
    name: str | None,
    company: str | None,
    designation: str | None,
    looking_for: str | None,
    offerings: str | None,
    ideal_connection: str | None,
    biggest_opportunity: str | None,
) -> str:
    fields = {
        "Name": name,
        "Company": company,
        "Designation": designation,
        "Looking for": looking_for,
        "Offerings": offerings,
        "Ideal connection": ideal_connection,
        "Biggest opportunity": biggest_opportunity,
    }
    lines = [f"{label}: {value}" for label, value in fields.items() if value]
    return "=== PARTICIPANT (from Excel, verbatim) ===\n" + "\n".join(lines)


def _format_linkedin(profile: dict[str, str]) -> str:
    order = ("name", "title", "company", "about")
    lines = [f"{_label(key)}: {profile[key]}" for key in order if profile.get(key)]
    return "\n".join(lines)


def _format_dict(data: dict[str, Any]) -> str:
    return "\n".join(f"{_label(key)}: {_format_value(value)}" for key, value in data.items() if value)


def _label(key: str) -> str:
    return key.replace("_", " ").title()


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)
