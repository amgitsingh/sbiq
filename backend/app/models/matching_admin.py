from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Ported from IndMatchmaking (D:\Python\IndMatchmaking\src\app\db\models\_matching.py
# and _profile.py) as part of docs/PLAN.md Phase 8 (merge). Unlike
# app/models/rbac.py / user.py (straight ports, no reconciliation needed),
# these are re-targeted per the merge's "eliminate shadow-table duplication"
# decision - see each class's own comment for what changed and why.


class EventParticipantMapping(Base):
    """Registered platform users assigned/collaborating on an event.

    Distinct from Participant (an uploaded Excel row, almost never a real
    login account) - this tracks which UserMaster accounts have visibility
    into or manage a given event. event_id now points at this repo's own
    integer-keyed `events` table (was a UUID FK to IndMatchmaking's own,
    now-dropped, event_master table).
    """

    __tablename__ = "event_participant_mapping"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_participant_mapping_event_user"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_master.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_master.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class SmtpMaster(Base):
    """Per-user SMTP configuration - no reconciliation needed, ported as-is
    (only references user_master, which already exists post-Task-50)."""

    __tablename__ = "smtp_master"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_master.id", ondelete="CASCADE"), index=True
    )
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(255))
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    encryption_type: Mapped[str | None] = mapped_column(String(40))
    from_email: Mapped[str] = mapped_column(String(255))
    from_name: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MatchProfile(Base):
    """Vestigial matrimonial-style candidate profile - carried over as-is
    per the merge decision, unrelated to and not FK'd to anything else in
    the schema (ported unchanged from IndMatchmaking's _profile.py)."""

    __tablename__ = "match_profiles"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    gender: Mapped[str] = mapped_column(String(30), index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    marital_status: Mapped[str | None] = mapped_column(String(80))
    religion: Mapped[str | None] = mapped_column(String(100))
    caste: Mapped[str | None] = mapped_column(String(100))
    mother_tongue: Mapped[str | None] = mapped_column(String(100))
    education: Mapped[str | None] = mapped_column(String(160))
    occupation: Mapped[str | None] = mapped_column(String(160))
    annual_income: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    height_cm: Mapped[int | None] = mapped_column(Integer)
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    family_details: Mapped[str | None] = mapped_column(Text)
    expectations: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmailLog(Base):
    """Match-email send audit trail - genuinely new (QBCals'
    send_match_email had no audit trail before this merge).

    Re-targeted from IndMatchmaking's original shape, not a straight port:
    the old sender_user_id/receiver_user_id (UUID FKs to user_master) plus a
    string-only external_recipient_id fallback existed because, pre-merge,
    IndMatchmaking had no real FK into QBCals' data at all. Post-merge, both
    sender and receiver of a match email are always real QBCals Participant
    rows (match emails are sent participant-to-participant, not
    account-to-account - most Participants never have a UserMaster login at
    all) - so both become plain integer FKs into `participants`, and the old
    string fallback is dropped as unnecessary. triggered_by_user_id is new:
    which admin (UserMaster) clicked "send," distinct from which
    participant's persona the email was sent as/to.
    """

    __tablename__ = "email_log"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("events.id", ondelete="SET NULL"))
    match_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("matches.id", ondelete="SET NULL"))
    sender_participant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("participants.id", ondelete="SET NULL")
    )
    receiver_participant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("participants.id", ondelete="SET NULL")
    )
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_master.id", ondelete="SET NULL")
    )
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
