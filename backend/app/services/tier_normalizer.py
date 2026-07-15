from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.models.participant import MembershipTier

logger = logging.getLogger(__name__)

# Values that unambiguously identify a specific tier. Deliberately excludes
# "yes" — a bare affirmative confirms membership but not which paid tier, so
# it's treated as ambiguous (see normalize_tier) rather than guessed here.
KNOWN_TIER_VARIANTS: dict[str, MembershipTier] = {
    "no": MembershipTier.non_member,
    "non member": MembershipTier.non_member,
    "non-member": MembershipTier.non_member,
    "not a member": MembershipTier.non_member,
    "geen lid": MembershipTier.non_member,
    "geen": MembershipTier.non_member,
    "sponsor": MembershipTier.sponsor,
    "sponsor member": MembershipTier.sponsor,
    "premium member": MembershipTier.premium_member,
    "premium lid": MembershipTier.premium_member,
    "premium": MembershipTier.premium_member,
    "business member": MembershipTier.business_member,
    "business partner": MembershipTier.business_member,
    "zakelijk lid": MembershipTier.business_member,
    "business": MembershipTier.business_member,
    "normal member": MembershipTier.normal_member,
    "standard member": MembershipTier.normal_member,
    "gewoon lid": MembershipTier.normal_member,
    "regulier lid": MembershipTier.normal_member,
    "member": MembershipTier.normal_member,
    "lid": MembershipTier.normal_member,
}


@dataclass
class TierResult:
    tier: str
    flagged: bool
    reason: str | None = None


def _normalize(value: str) -> str:
    v = value.strip().lower()
    v = re.sub(r"[^\w\s]", " ", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v


def normalize_tier(raw_value) -> TierResult:
    """Map a free-text membership value to a canonical MembershipTier.

    Blank/missing -> normal_member (no answer given, not an error).
    Known variant (English/Dutch) -> its exact tier.
    Ambiguous ("Yes") or unrecognized garbage -> business_member, flagged
    for admin review (confirmed decision: don't silently under-credit a
    participant who indicated *some* form of membership).
    """
    if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
        return TierResult(tier=MembershipTier.normal_member.value, flagged=False)

    normalized = _normalize(str(raw_value))

    if normalized == "yes":
        logger.info(f"Ambiguous membership value {raw_value!r} -> business_member, flagged for review")
        return TierResult(
            tier=MembershipTier.business_member.value,
            flagged=True,
            reason=f"ambiguous membership value {raw_value!r} - confirmed member but tier unclear, defaulted to business_member",
        )

    if normalized in KNOWN_TIER_VARIANTS:
        return TierResult(tier=KNOWN_TIER_VARIANTS[normalized].value, flagged=False)

    logger.warning(f"Unrecognized membership value {raw_value!r} -> business_member, flagged for review")
    return TierResult(
        tier=MembershipTier.business_member.value,
        flagged=True,
        reason=f"unrecognized membership value {raw_value!r} - defaulted to business_member",
    )
