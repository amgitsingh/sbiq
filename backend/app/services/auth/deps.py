from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_database import get_async_db
from app.models.user import UserMaster
from app.services.auth.security import decode_access_token

# Ported from IndMatchmaking (D:\Python\IndMatchmaking\src\app\domain\auth\deps.py)
# as part of docs/PLAN.md Phase 8 (Task 56).

bearer = HTTPBearer(auto_error=False)


async def current_admin_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_async_db),
) -> UserMaster:
    """Return the authenticated user (must have an admin-level role)."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(str(payload["sub"]))
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user = await db.scalar(select(UserMaster).where(UserMaster.id == user_id, UserMaster.status == "active"))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


# Alias matching IndMatchmaking's naming - used by every ported router's
# `Depends(current_admin)` (Stage 8.4 onward).
current_admin = current_admin_user
