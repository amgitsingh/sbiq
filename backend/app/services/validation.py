from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.services.header_mapper import resolve_name

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ValidatedRow:
    row_number: int | None
    data: dict
    reasons: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    valid: list[ValidatedRow]
    flagged: list[ValidatedRow]
    rejected: list[ValidatedRow]


def _normalize_whitespace(value):
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip())
    return value


def _clean_row(mapped_row: dict) -> dict:
    return {key: _normalize_whitespace(value) for key, value in mapped_row.items()}


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_rows(mapped_rows: list[dict]) -> ValidationResult:
    """Validate header-mapped participant rows into three buckets.

    Required (reject if missing): name, email, company. Email format is
    also checked. Warn-level (flag, don't drop): looking_for + offerings
    both blank. Rows sharing a normalized email are treated as re-submissions
    of the same person - the latest row is kept and flagged for review;
    earlier ones are rejected as superseded.
    """
    rejected: list[ValidatedRow] = []
    passed: list[ValidatedRow] = []  # candidates for valid/flagged, pre-dedup

    for raw_row in mapped_rows:
        row_number = raw_row.get("__row_number")
        row = _clean_row({k: v for k, v in raw_row.items() if not k.startswith("__")})

        name = resolve_name(row)
        if name:
            row["name"] = name

        reasons: list[str] = []

        if _is_blank(row.get("name")):
            reasons.append("missing required field: name")

        if _is_blank(row.get("email")):
            reasons.append("missing required field: email")
        elif not EMAIL_RE.match(row["email"]):
            reasons.append(f"invalid email format: {row['email']!r}")

        if _is_blank(row.get("company")):
            reasons.append("missing required field: company")

        if reasons:
            logger.info(f"Row {row_number} rejected: {'; '.join(reasons)}")
            rejected.append(ValidatedRow(row_number, row, reasons))
            continue

        if _is_blank(row.get("looking_for")) and _is_blank(row.get("offerings")):
            reasons.append("no looking_for or offerings - needs manual review")

        passed.append(ValidatedRow(row_number, row, reasons))

    valid, flagged, deduped_rejected = _dedupe_by_email(passed)
    rejected.extend(deduped_rejected)

    return ValidationResult(valid=valid, flagged=flagged, rejected=rejected)


def _dedupe_by_email(
    passed: list[ValidatedRow],
) -> tuple[list[ValidatedRow], list[ValidatedRow], list[ValidatedRow]]:
    valid: list[ValidatedRow] = []
    flagged: list[ValidatedRow] = []
    rejected: list[ValidatedRow] = []

    by_email: dict[str, list[ValidatedRow]] = {}
    for item in passed:
        key = item.data["email"].strip().lower()
        by_email.setdefault(key, []).append(item)

    for items in by_email.values():
        items.sort(key=lambda i: i.row_number if i.row_number is not None else -1)
        latest = items[-1]
        earlier = items[:-1]

        for dup in earlier:
            dup.reasons.append(f"duplicate email - superseded by row {latest.row_number}")
            logger.info(f"Row {dup.row_number} rejected: superseded by row {latest.row_number}")
            rejected.append(dup)

        if earlier:
            latest.reasons.append(f"duplicate submission - kept latest of {len(items)} (verify answers)")

        if latest.reasons:
            flagged.append(latest)
        else:
            valid.append(latest)

    return valid, flagged, rejected
