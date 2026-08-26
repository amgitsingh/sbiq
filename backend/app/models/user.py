from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.rbac import RoleMaster

# Ported from IndMatchmaking (D:\Python\IndMatchmaking\src\app\db\models\_matching.py)
# as part of docs/PLAN.md Phase 8 (merge) - see app/models/rbac.py's header
# comment for the house-style adaptation rationale (same here).


class UserMaster(Base):
    """Single user table for admins, users, and participants."""

    __tablename__ = "user_master"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    mobile_phone: Mapped[str | None] = mapped_column(String(40))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("company_master.id", ondelete="SET NULL")
    )
    company_name: Mapped[str | None] = mapped_column(String(255))
    job_title: Mapped[str | None] = mapped_column(String(160))
    industry: Mapped[str | None] = mapped_column(Text, index=True)
    company_size: Mapped[int | None] = mapped_column(Integer)
    looking_for: Mapped[str | None] = mapped_column(Text)
    offering: Mapped[str | None] = mapped_column(Text)
    target_connections: Mapped[str | None] = mapped_column(Text)
    registration_message: Mapped[str | None] = mapped_column(Text)
    member_status: Mapped[str | None] = mapped_column(String(40), index=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("role_master.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_master.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    role: Mapped[RoleMaster | None] = relationship("RoleMaster", lazy="select")
