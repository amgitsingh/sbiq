"""Owner-scoped SMTP configuration routes.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\smtp\\controller.py)
as part of docs/PLAN.md Phase 8 (Task 60).
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_database import get_async_db
from app.models.matching_admin import SmtpMaster
from app.models.user import UserMaster
from app.services.auth.deps import current_admin
from app.services.auth.security import decrypt_credential, encrypt_credential
from app.services.microsoft_graph_mail import (
    MicrosoftGraphMailError,
    is_microsoft_graph_mail_configured,
    test_microsoft_graph_mail_credentials,
)

router = APIRouter(prefix="/admin/smtp", tags=["smtp"])

EncryptionType = Literal["none", "starttls", "ssl"]


class SmtpSettingsBase(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    encryption_type: EncryptionType = "starttls"
    from_email: EmailStr
    from_name: str | None = Field(default=None, max_length=160)
    status: Literal["active", "inactive"] = "active"


class SmtpSettingsWrite(SmtpSettingsBase):
    password: str | None = Field(default=None, max_length=500)


class SmtpSettingsRead(SmtpSettingsBase):
    id: uuid.UUID
    has_password: bool
    updated_at: datetime


class SmtpTestResult(BaseModel):
    success: bool
    message: str


async def _current_settings(user_id: uuid.UUID, db: AsyncSession) -> SmtpMaster | None:
    rows = await db.scalars(select(SmtpMaster).where(SmtpMaster.user_id == user_id).order_by(SmtpMaster.updated_at.desc()))
    return rows.first()


def _serialize(row: SmtpMaster) -> SmtpSettingsRead:
    return SmtpSettingsRead(
        id=row.id,
        host=row.host,
        port=row.port,
        username=row.username,
        encryption_type=row.encryption_type or "none",
        from_email=row.from_email,
        from_name=row.from_name,
        status=row.status,
        has_password=bool(row.password_encrypted),
        updated_at=row.updated_at,
    )


def _test_connection(payload: SmtpSettingsWrite, password: str | None) -> None:
    timeout = 15
    if payload.encryption_type == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(payload.host, payload.port, timeout=timeout, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(payload.host, payload.port, timeout=timeout)

    with client:
        client.ehlo()
        if payload.encryption_type == "starttls":
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if payload.username:
            if not password:
                raise ValueError("SMTP password is required for authentication")
            client.login(payload.username, password)
        client.noop()


@router.get("", response_model=SmtpSettingsRead | None)
async def get_smtp_settings(
    user: UserMaster = Depends(current_admin), db: AsyncSession = Depends(get_async_db)
) -> SmtpSettingsRead | None:
    """Return the authenticated user's SMTP settings without the password."""
    row = await _current_settings(user.id, db)
    return _serialize(row) if row else None


@router.put("", response_model=SmtpSettingsRead)
async def save_smtp_settings(
    payload: SmtpSettingsWrite, user: UserMaster = Depends(current_admin), db: AsyncSession = Depends(get_async_db)
) -> SmtpSettingsRead:
    """Create or update the authenticated user's SMTP settings."""
    row = await _current_settings(user.id, db)
    if row is None:
        if payload.username and not payload.password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SMTP password is required")
        row = SmtpMaster(user_id=user.id)
        db.add(row)

    row.host = payload.host
    row.port = payload.port
    row.username = payload.username
    row.encryption_type = payload.encryption_type
    row.from_email = str(payload.from_email)
    row.from_name = payload.from_name
    row.status = payload.status
    if payload.password:
        row.password_encrypted = encrypt_credential(payload.password)
    elif not payload.username:
        row.password_encrypted = None

    await db.commit()
    await db.refresh(row)
    return _serialize(row)


@router.post("/test", response_model=SmtpTestResult)
async def test_smtp_settings(
    payload: SmtpSettingsWrite, user: UserMaster = Depends(current_admin), db: AsyncSession = Depends(get_async_db)
) -> SmtpTestResult:
    """Verify connection, encryption negotiation, and authentication without sending email."""
    if is_microsoft_graph_mail_configured():
        try:
            await test_microsoft_graph_mail_credentials()
        except MicrosoftGraphMailError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Microsoft Graph mail authentication failed: {exc}"
            ) from exc
        return SmtpTestResult(success=True, message="Microsoft Graph mail credentials were accepted. Email sending will use Graph Mail.Send.")

    password = payload.password
    if payload.username and not password:
        row = await _current_settings(user.id, db)
        if row and row.password_encrypted:
            try:
                password = decrypt_credential(row.password_encrypted)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stored SMTP password cannot be decrypted"
                ) from exc

    try:
        await asyncio.to_thread(_test_connection, payload, password)
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"SMTP connection failed: {exc}") from exc
    return SmtpTestResult(success=True, message="SMTP connection and authentication succeeded")
