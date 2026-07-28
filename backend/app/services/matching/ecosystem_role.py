from __future__ import annotations

from collections import defaultdict

# Per-participant ecosystem role taxonomy, verbatim from the client's
# examples.docx ("Proposed SBIQ Rule" section) - see
# docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md, Item 2. Classifies WHAT ROLE a
# participant plays in the business ecosystem (access, influence, capital,
# deal flow, network reach) rather than what they sell - the client's core
# argument is that industry/title similarity is often the wrong signal for a
# genuinely valuable introduction.
ECOSYSTEM_ROLES = [
    "Direct Buyer",
    "Direct Seller",
    "Network Multiplier",
    "Ecosystem Builder",
    "Investor",
    "Deal Flow Source",
    "Strategic Connector",
    "Market Access Partner",
    "Community Leader",
    "Specialist Advisor",
    "Corporate Entry Point",
]

# Symmetric pairs - built into a bidirectional lookup below, same pattern as
# sector_size.SECTOR_ADJACENCY so adjacency can't drift out of sync. This is
# the most subjective part of this module - a first proposal, not a settled
# taxonomy; tune based on real matching outcomes.
_ADJACENT_PAIRS: list[tuple[str, str]] = [
    ("Direct Buyer", "Direct Seller"),
    ("Direct Buyer", "Market Access Partner"),
    ("Direct Buyer", "Corporate Entry Point"),
    ("Direct Seller", "Investor"),
    ("Direct Seller", "Deal Flow Source"),
    ("Direct Seller", "Corporate Entry Point"),
    ("Direct Seller", "Market Access Partner"),
    ("Investor", "Deal Flow Source"),
    ("Investor", "Strategic Connector"),
    ("Investor", "Corporate Entry Point"),
    ("Deal Flow Source", "Network Multiplier"),
    ("Network Multiplier", "Community Leader"),
    ("Network Multiplier", "Strategic Connector"),
    ("Network Multiplier", "Ecosystem Builder"),
    ("Ecosystem Builder", "Community Leader"),
    ("Ecosystem Builder", "Strategic Connector"),
    ("Ecosystem Builder", "Market Access Partner"),
    ("Strategic Connector", "Corporate Entry Point"),
    ("Market Access Partner", "Ecosystem Builder"),
    ("Market Access Partner", "Corporate Entry Point"),
    ("Community Leader", "Specialist Advisor"),
    ("Specialist Advisor", "Direct Buyer"),
    ("Specialist Advisor", "Direct Seller"),
    ("Specialist Advisor", "Corporate Entry Point"),
]

ROLE_ADJACENCY: dict[str, set[str]] = defaultdict(set)
for _a, _b in _ADJACENT_PAIRS:
    ROLE_ADJACENCY[_a].add(_b)
    ROLE_ADJACENCY[_b].add(_a)


def role_adjacency_score(a_role: str | None, b_role: str | None) -> float:
    """1.0 if the two roles are complementary (in each other's adjacency
    set), else 0.0 - including when either side is missing/unclassified (no
    data means no confidence, not a free pass) and when the roles are
    IDENTICAL (deliberately not rewarded - two participants with the same
    ecosystem role are usually competing for the same counterparts, not a
    complementary match, per the client's own thesis in
    docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md Item 2).
    """
    if not a_role or not b_role:
        return 0.0
    if a_role == b_role:
        return 0.0
    return 1.0 if b_role in ROLE_ADJACENCY[a_role] else 0.0
