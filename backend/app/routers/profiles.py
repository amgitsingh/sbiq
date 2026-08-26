"""Profile (MatchProfile) admin routes.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\profiles\\controller.py)
as part of docs/PLAN.md Phase 8 (Task 60). MatchProfile itself is carried
over as-is per the merge decision (vestigial matrimonial-style domain,
unrelated to real event-matchmaking, kept unchanged rather than dropped).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_database import get_async_db
from app.models.matching_admin import MatchProfile
from app.services.auth.deps import current_admin

router = APIRouter(prefix="/admin/profiles", tags=["profiles"], dependencies=[Depends(current_admin)])


class ProfileBase(BaseModel):
    profile_code: str = Field(min_length=2, max_length=40)
    full_name: str = Field(min_length=2, max_length=160)
    gender: str
    date_of_birth: date | None = None
    marital_status: str | None = None
    religion: str | None = None
    caste: str | None = None
    mother_tongue: str | None = None
    education: str | None = None
    occupation: str | None = None
    annual_income: Decimal | None = None
    height_cm: int | None = Field(default=None, ge=90, le=240)
    city: str | None = None
    state: str | None = None
    country: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    family_details: str | None = None
    expectations: str | None = None
    status: str = "active"


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    gender: str | None = None
    date_of_birth: date | None = None
    marital_status: str | None = None
    religion: str | None = None
    caste: str | None = None
    mother_tongue: str | None = None
    education: str | None = None
    occupation: str | None = None
    annual_income: Decimal | None = None
    height_cm: int | None = Field(default=None, ge=90, le=240)
    city: str | None = None
    state: str | None = None
    country: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    family_details: str | None = None
    expectations: str | None = None
    status: str | None = None


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ProfileList(BaseModel):
    items: list[ProfileRead]
    total: int


@router.get("", response_model=ProfileList)
async def list_profiles(
    q: str | None = None,
    gender: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_async_db),
) -> ProfileList:
    """List profiles with filters."""
    statement = select(MatchProfile)
    count_statement = select(func.count()).select_from(MatchProfile)
    filters = []
    if q:
        query = f"%{q}%"
        filters.append(or_(MatchProfile.full_name.ilike(query), MatchProfile.profile_code.ilike(query)))
    if gender:
        filters.append(MatchProfile.gender == gender)
    if status_filter:
        filters.append(MatchProfile.status == status_filter)
    if filters:
        statement = statement.where(*filters)
        count_statement = count_statement.where(*filters)
    total = await db.scalar(count_statement)
    rows = await db.scalars(statement.order_by(MatchProfile.created_at.desc()).limit(limit).offset(offset))
    return ProfileList(items=[ProfileRead.model_validate(row) for row in rows], total=total or 0)


@router.post("", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
async def create_profile(payload: ProfileCreate, db: AsyncSession = Depends(get_async_db)) -> MatchProfile:
    """Create a profile."""
    existing = await db.scalar(select(MatchProfile).where(MatchProfile.profile_code == payload.profile_code))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile code already exists")
    profile = MatchProfile(**payload.model_dump())
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=ProfileRead)
async def get_profile(profile_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)) -> MatchProfile:
    """Get a profile by id."""
    profile = await db.get(MatchProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


@router.patch("/{profile_id}", response_model=ProfileRead)
async def update_profile(
    profile_id: uuid.UUID, payload: ProfileUpdate, db: AsyncSession = Depends(get_async_db)
) -> MatchProfile:
    """Update a profile."""
    profile = await db.get(MatchProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_profile(profile_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)) -> None:
    """Delete a profile."""
    profile = await db.get(MatchProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    await db.delete(profile)
    await db.commit()
