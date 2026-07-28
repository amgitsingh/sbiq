from __future__ import annotations

# Keyword-based seniority classifier from free-text `designation`. Real
# submitted data mixes English and Dutch titles (confirmed against sample
# data - e.g. "directeur/eigenaar", "Creative Director", "CEO"), so both are
# covered. Senior titles genuinely hold decision-making authority; mid-level
# titles have some influence but aren't the final decision-maker; anything
# else (or blank/unparseable) is treated as unclassifiable, same "no data
# means no confidence" convention as sector_size.sector_alignment_score.
SENIOR_TITLE_KEYWORDS = [
    "ceo", "cfo", "coo", "cto", "cmo", "chief",
    "founder", "co-founder", "cofounder", "oprichter",
    "owner", "eigenaar", "dga",
    "president", "vice president", " vp ",
    "director", "directeur", "managing director",
    "partner", "principal",
]

MID_TITLE_KEYWORDS = [
    "manager", "head of", "lead", "senior",
]


def classify_seniority(designation: str | None) -> float:
    """1.0 senior/decision-maker, 0.5 mid-level, 0.0 unclassifiable."""
    if not designation:
        return 0.0
    text = f" {designation.strip().lower()} "
    if any(kw in text for kw in SENIOR_TITLE_KEYWORDS):
        return 1.0
    if any(kw in text for kw in MID_TITLE_KEYWORDS):
        return 0.5
    return 0.0


def decision_authority_score(a_designation: str | None, b_designation: str | None) -> float:
    """Symmetric pair score in [0, 1] - average of both sides' seniority.

    Rewards pairs where both participants hold real decision-making
    authority (per the client's stated priority for "decision-makers,
    innovation managers, transformation leaders, business developers" in
    docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md, Item 1), not just one side.
    """
    a_score = classify_seniority(a_designation)
    b_score = classify_seniority(b_designation)
    return (a_score + b_score) / 2
