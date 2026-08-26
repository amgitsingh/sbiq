"""Self-service account profile routes.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\account\\controller.py)
as part of docs/PLAN.md Phase 8 (Task 57).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_database import get_async_db
from app.models.rbac import RoleMaster
from app.models.user import UserMaster
from app.services.auth.deps import current_admin

router = APIRouter(prefix="/account/profile", tags=["account"])


class AccountProfileRead(BaseModel):
    id: str
    email: EmailStr
    first_name: str
    last_name: str | None = None
    mobile_phone: str | None = None
    company_name: str | None = None
    job_title: str | None = None
    industry: str | None = None
    company_size: int | None = None
    looking_for: str | None = None
    offering: str | None = None
    target_connections: str | None = None
    registration_message: str | None = None
    member_status: str | None = None
    status: str
    role_name: str


class AccountProfileUpdate(BaseModel):
    first_name: str
    last_name: str | None = None
    mobile_phone: str | None = None
    company_name: str | None = None
    job_title: str | None = None
    industry: str | None = None
    company_size: int | None = None
    looking_for: str | None = None
    offering: str | None = None
    target_connections: str | None = None


async def _serialize(user: UserMaster, db: AsyncSession) -> AccountProfileRead:
    role = await db.get(RoleMaster, user.role_id) if user.role_id else None
    return AccountProfileRead(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        mobile_phone=user.mobile_phone,
        company_name=user.company_name,
        job_title=user.job_title,
        industry=user.industry,
        company_size=user.company_size,
        looking_for=user.looking_for,
        offering=user.offering,
        target_connections=user.target_connections,
        registration_message=user.registration_message,
        member_status=user.member_status,
        status=user.status,
        role_name=role.role_name if role else "Unknown",
    )


@router.get("", response_model=AccountProfileRead)
async def get_account_profile(
    user: UserMaster = Depends(current_admin), db: AsyncSession = Depends(get_async_db)
) -> AccountProfileRead:
    """Return the logged-in user's editable profile."""
    return await _serialize(user, db)


@router.put("", response_model=AccountProfileRead)
async def update_account_profile(
    payload: AccountProfileUpdate,
    user: UserMaster = Depends(current_admin),
    db: AsyncSession = Depends(get_async_db),
) -> AccountProfileRead:
    """Update the logged-in user's profile details."""
    first_name = payload.first_name.strip()
    if not first_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="First name is required")

    user.first_name = first_name
    user.last_name = (payload.last_name or "").strip() or None
    user.mobile_phone = (payload.mobile_phone or "").strip() or None
    user.company_name = (payload.company_name or "").strip() or None
    user.job_title = (payload.job_title or "").strip() or None
    user.industry = (payload.industry or "").strip() or None
    user.company_size = payload.company_size
    user.looking_for = (payload.looking_for or "").strip() or None
    user.offering = (payload.offering or "").strip() or None
    user.target_connections = (payload.target_connections or "").strip() or None

    await db.commit()
    await db.refresh(user)
    return await _serialize(user, db)
