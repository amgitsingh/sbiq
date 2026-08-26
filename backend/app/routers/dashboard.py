"""Admin dashboard routes.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\dashboard\\controller.py)
as part of docs/PLAN.md Phase 8 (Task 60).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_database import get_async_db
from app.models.matching_admin import MatchProfile
from app.services.auth.deps import current_admin

router = APIRouter(prefix="/admin/dashboard", tags=["dashboard"], dependencies=[Depends(current_admin)])


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_async_db)) -> dict[str, int]:
    """Return profile counts for the admin dashboard."""
    total = await db.scalar(select(func.count()).select_from(MatchProfile))
    active = await db.scalar(select(func.count()).select_from(MatchProfile).where(MatchProfile.status == "active"))
    inactive = await db.scalar(select(func.count()).select_from(MatchProfile).where(MatchProfile.status == "inactive"))
    return {"total_profiles": total or 0, "active_profiles": active or 0, "inactive_profiles": inactive or 0}
