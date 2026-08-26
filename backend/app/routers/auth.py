from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.async_database import get_async_db
from app.models.rbac import RoleMaster
from app.models.user import UserMaster
from app.services.auth.deps import current_admin
from app.services.auth.security import create_access_token, verify_password

# Ported from IndMatchmaking (D:\Python\IndMatchmaking\src\app\domain\auth\controller.py)
# as part of docs/PLAN.md Phase 8 (Task 56). Request/response models kept
# inline in the router file rather than a separate schemas.py, matching this
# repo's existing convention (see app/routers/events.py).

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_ROLES = {"Super Admin", "Admin", "User"}


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str | None = None
    status: str
    role_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserOut


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_async_db)) -> TokenResponse:
    """Authenticate a user with an admin-level role."""
    user = await db.scalar(
        select(UserMaster)
        .where(UserMaster.email == payload.email.lower(), UserMaster.status == "active")
        .options(selectinload(UserMaster.role))
    )
    if user is None or user.password_hash is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    role_name = user.role.role_name if user.role else None
    if role_name not in LOGIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    token = create_access_token(str(user.id), {"email": user.email, "role_name": role_name})
    user_out = AuthUserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        status=user.status,
        role_name=role_name,
    )
    return TokenResponse(access_token=token, user=user_out)


@router.get("/me", response_model=AuthUserOut)
async def me(user: UserMaster = Depends(current_admin), db: AsyncSession = Depends(get_async_db)) -> AuthUserOut:
    """Return the authenticated user."""
    role = await db.get(RoleMaster, user.role_id) if user.role_id else None
    return AuthUserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        status=user.status,
        role_name=role.role_name if role else "Unknown",
    )
