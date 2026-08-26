"""Lookup routes for forms.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\lookups\\controller.py)
as part of docs/PLAN.md Phase 8 (Task 60).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth.deps import current_admin

router = APIRouter(prefix="/admin/lookups", tags=["lookups"], dependencies=[Depends(current_admin)])


@router.get("")
async def lookups() -> dict[str, list[str]]:
    """Return option sets used by the admin UI."""
    return {
        "genders": ["male", "female", "other"],
        "statuses": ["active", "inactive", "matched", "archived"],
        "marital_statuses": ["never_married", "divorced", "widowed", "awaiting_divorce"],
        "religions": ["Hindu", "Muslim", "Christian", "Sikh", "Jain", "Buddhist", "Other"],
    }
