from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_database import get_async_db
from app.models.rbac import RoleMaster
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


def require_role(*role_names: str):
    """Dependency factory: authenticate via current_admin, then additionally
    require the user's role to be one of role_names.

    New in this merge (Task 58) - IndMatchmaking only had ad hoc inline
    checks scattered across routers (e.g. `if role.role_name != "Super
    Admin": raise HTTPException(403)` in registrations/controller.py). This
    gives QBCals' own routers (Task 59 onward) one consistent, reusable way
    to gate a route by role instead of repeating that pattern.

    Loads the role by role_id via db.get() rather than accessing
    `user.role` directly - lazy-loading a relationship outside an active
    async context raises MissingGreenlet, so every role lookup in this
    codebase goes through an explicit db.get(RoleMaster, ...) call instead
    (same pattern already used in auth.py's /me and registrations.py).
    """

    async def dependency(
        user: UserMaster = Depends(current_admin),
        db: AsyncSession = Depends(get_async_db),
    ) -> UserMaster:
        role = await db.get(RoleMaster, user.role_id) if user.role_id else None
        role_name = role.role_name if role else None
        if role_name not in role_names:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return dependency
