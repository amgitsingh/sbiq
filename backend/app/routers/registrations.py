# ruff: noqa: E501
"""Public registration and admin approval routes.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\registrations\\controller.py)
as part of docs/PLAN.md Phase 8 (Task 57). Adapted: reads the module-level
`settings` singleton directly instead of `Depends(get_settings)`; uses this
repo's `get_async_db`/`current_admin`; router paths drop the `/api` prefix,
matching the precedent already set in app/routers/auth.py (Task 56) - final
path decisions get revisited at the Task 68 "collapse /api/studio/*"
checkpoint anyway, so this isn't locked in.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_database import get_async_db
from app.core.config import settings
from app.models.matching_admin import EmailLog, SmtpMaster
from app.models.rbac import RoleMaster
from app.models.user import UserMaster
from app.services.auth.deps import current_admin
from app.services.auth.security import decrypt_credential, hash_password
from app.services.microsoft_graph_mail import (
    MicrosoftGraphMailError,
    is_microsoft_graph_mail_configured,
    send_microsoft_graph_mail,
)

router = APIRouter(tags=["registrations"])

PHONE_PATTERN = re.compile(r"^\+?[0-9\s\-()]{7,20}$")


class RegistrationRequest(BaseModel):
    first_name: str
    last_name: str | None = None
    email: EmailStr
    phone: str
    company: str | None = None
    message: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        candidate = value.strip()
        if not PHONE_PATTERN.match(candidate):
            raise ValueError("Enter a valid phone number.")
        digits = re.sub(r"\D", "", candidate)
        if not (7 <= len(digits) <= 15):
            raise ValueError("Phone number must contain 7 to 15 digits.")
        return candidate


class RegistrationResponse(BaseModel):
    success: bool
    message: str


class RegistrationDecisionResponse(BaseModel):
    success: bool
    message: str
    user_id: UUID
    status: str


def _generate_password(length: int = 12) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _user_role(db: AsyncSession) -> RoleMaster:
    role = await db.scalar(select(RoleMaster).where(RoleMaster.role_name == "User"))
    if role is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User role is not configured")
    return role


async def _ensure_super_admin(user: UserMaster, db: AsyncSession) -> None:
    role = await db.get(RoleMaster, user.role_id) if user.role_id else None
    if role is None or role.role_name != "Super Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only Super Admin can review registration requests."
        )


async def _active_smtp(user_id: UUID, db: AsyncSession) -> SmtpMaster:
    row = await db.scalar(
        select(SmtpMaster).where(SmtpMaster.user_id == user_id, SmtpMaster.status == "active").order_by(SmtpMaster.updated_at.desc())
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Configure active SMTP settings before activating registrations."
        )
    return row


async def _system_smtp(db: AsyncSession) -> SmtpMaster | None:
    """Best-effort SMTP sender identity for emails triggered by public (unauthenticated) requests."""
    return await db.scalar(
        select(SmtpMaster)
        .join(UserMaster, UserMaster.id == SmtpMaster.user_id)
        .join(RoleMaster, RoleMaster.id == UserMaster.role_id)
        .where(SmtpMaster.status == "active", RoleMaster.role_name == "Super Admin")
        .order_by(SmtpMaster.updated_at.desc())
    )


async def _ensure_unique_contact(email: str, phone: str, db: AsyncSession) -> None:
    existing_email = await db.scalar(select(UserMaster).where(UserMaster.email == email))
    if existing_email is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account request already exists for this email address."
        )
    existing_phone = await db.scalar(select(UserMaster).where(UserMaster.mobile_phone == phone))
    if existing_phone is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account request already exists for this phone number."
        )


def _activation_email_html(*, application_url: str, email: str, first_name: str, password: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SBIQ Account Activated</title>
  <style type="text/css">
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    img {{ -ms-interpolation-mode: bicubic; border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
    @media screen and (max-width: 600px) {{
      .email-container {{ width: 100% !important; margin: auto !important; border-radius: 0 !important; }}
      .content-padding {{ padding: 24px 20px !important; }}
      .header-padding {{ padding: 20px !important; }}
      .footer-padding {{ padding: 24px 20px !important; }}
      .mobile-btn {{ display: block !important; width: 100% !important; box-sizing: border-box !important; }}
      .mobile-text-h1 {{ font-size: 22px !important; }}
      .mobile-text-p {{ font-size: 15px !important; }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; -webkit-font-smoothing: antialiased; width: 100% !important;">
  <table width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="#f3f4f6" style="width: 100%; background-color: #f3f4f6; border-collapse: collapse;">
    <tr>
      <td align="center" style="padding: 30px 10px;">
        <table class="email-container" width="100%" border="0" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; max-width: 600px; width: 100%; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05); border: 1px solid #e5e7eb; border-collapse: collapse;">
          <tr>
            <td align="left" class="header-padding" style="padding: 25px 30px; border-bottom: 1px solid #f3f4f6;">
              <table border="0" cellpadding="0" cellspacing="0" style="margin: 0; border-collapse: collapse;">
                <tr>
                  <td align="center" valign="middle" style="padding-right: 20px;">
                    <img src="https://dev.sbiq.ai/images/sbiq1.png" alt="SBIQ Logo" width="140" style="display: block; max-width: 140px; height: auto;">
                  </td>
                  <td align="center" valign="middle">
                    <img src="https://amsterdam.meerbusiness.nl/wp-content/uploads/2023/08/meerlogo.png" alt="MeerBusiness Logo" width="140" style="display: block; max-width: 140px; height: auto;">
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td class="content-padding" style="padding: 30px 35px 25px 35px; color: #4b5563;">
              <h1 class="mobile-text-h1" style="margin: 0 0 16px 0; font-size: 22px; font-weight: 700; color: #111827; letter-spacing: -0.3px; line-height: 1.3;">
                Your account is now active.
              </h1>
              <p class="mobile-text-p" style="margin: 0 0 12px 0; font-size: 15px; line-height: 1.6; color: #4b5563;">
                Hello {first_name},
              </p>
              <p class="mobile-text-p" style="margin: 0 0 18px 0; font-size: 15px; line-height: 1.6; color: #4b5563;">
                Your organization has confirmed your registration and your SBIQ account has been activated. You can now sign in using the credentials below.
              </p>
              <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 0 24px 0; border-collapse: collapse;">
                <tr>
                  <td style="padding: 16px; border: 1px solid #e5e7eb; border-radius: 8px; background: #f8fafc;">
                    <p style="margin: 0 0 8px 0; font-size: 14px; color: #111827;"><strong>Application URL:</strong> <a href="{application_url}" style="color: #0f172a;">{application_url}</a></p>
                    <p style="margin: 0 0 8px 0; font-size: 14px; color: #111827;"><strong>Email:</strong> {email}</p>
                    <p style="margin: 0; font-size: 14px; color: #111827;"><strong>Temporary Password:</strong> {password}</p>
                  </td>
                </tr>
              </table>
              <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 24px; border-collapse: collapse;">
                <tr>
                  <td align="center">
                    <table border="0" cellpadding="0" cellspacing="0" class="mobile-btn" style="border-collapse: collapse;">
                      <tr>
                        <td align="center" bgcolor="#0f172a" style="border-radius: 6px;">
                          <a href="{application_url}" class="mobile-btn" style="display: inline-block; padding: 12px 24px; font-size: 15px; font-weight: 600; color: #ffffff; text-decoration: none; border-radius: 6px; letter-spacing: 0.5px; background-color: #0f172a; border: 1px solid #0f172a;">
                            Open Application
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
              <p class="mobile-text-p" style="margin: 0; font-size: 15px; line-height: 1.6; color: #4b5563;">
                Best regards,<br>
                <strong style="font-weight: 600; color: #111827;">The SBIQ Team</strong>
              </p>
            </td>
          </tr>
          <tr>
            <td align="center" class="footer-padding" style="padding: 20px 30px; background-color: #f8fafc; border-top: 1px solid #e5e7eb; color: #94a3b8; font-size: 12px; line-height: 1.5;">
              <p style="margin: 0 0 6px 0;">&copy; 2026 SBIQ. All rights reserved.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _activation_email_text(*, application_url: str, email: str, first_name: str, password: str) -> str:
    return (
        f"Hello {first_name},\n\n"
        "Your organization has confirmed your registration and your SBIQ account is now active.\n\n"
        f"Application URL: {application_url}\n"
        f"Email: {email}\n"
        f"Temporary Password: {password}\n\n"
        "You can now use the system.\n\n"
        "Best regards,\n"
        "The SBIQ Team"
    )


def _registration_received_html(*, first_name: str, email: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SBIQ Registration Received</title>
  <style type="text/css">
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    img {{ -ms-interpolation-mode: bicubic; border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
    @media screen and (max-width: 600px) {{
      .email-container {{ width: 100% !important; margin: auto !important; border-radius: 0 !important; }}
      .content-padding {{ padding: 24px 20px !important; }}
      .header-padding {{ padding: 20px !important; }}
      .footer-padding {{ padding: 24px 20px !important; }}
      .mobile-text-h1 {{ font-size: 22px !important; }}
      .mobile-text-p {{ font-size: 15px !important; }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; -webkit-font-smoothing: antialiased; width: 100% !important;">
  <table width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="#f3f4f6" style="width: 100%; background-color: #f3f4f6; border-collapse: collapse;">
    <tr>
      <td align="center" style="padding: 30px 10px;">
        <table class="email-container" width="100%" border="0" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; max-width: 600px; width: 100%; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05); border: 1px solid #e5e7eb; border-collapse: collapse;">
          <tr>
            <td align="left" class="header-padding" style="padding: 25px 30px; border-bottom: 1px solid #f3f4f6;">
              <table border="0" cellpadding="0" cellspacing="0" style="margin: 0; border-collapse: collapse;">
                <tr>
                  <td align="center" valign="middle" style="padding-right: 20px;">
                    <img src="https://dev.sbiq.ai/images/sbiq1.png" alt="SBIQ Logo" width="140" style="display: block; max-width: 140px; height: auto;">
                  </td>
                  <td align="center" valign="middle">
                    <img src="https://amsterdam.meerbusiness.nl/wp-content/uploads/2023/08/meerlogo.png" alt="MeerBusiness Logo" width="140" style="display: block; max-width: 140px; height: auto;">
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td class="content-padding" style="padding: 30px 35px 25px 35px; color: #4b5563;">
              <h1 class="mobile-text-h1" style="margin: 0 0 16px 0; font-size: 22px; font-weight: 700; color: #111827; letter-spacing: -0.3px; line-height: 1.3;">
                We've received your registration.
              </h1>
              <p class="mobile-text-p" style="margin: 0 0 12px 0; font-size: 15px; line-height: 1.6; color: #4b5563;">
                Hello {first_name},
              </p>
              <p class="mobile-text-p" style="margin: 0 0 18px 0; font-size: 15px; line-height: 1.6; color: #4b5563;">
                Thank you for signing up for SBIQ using {email}. Your request is now pending review by an administrator.
                You'll receive a separate email with your login credentials as soon as your account is approved.
              </p>
              <p class="mobile-text-p" style="margin: 0; font-size: 15px; line-height: 1.6; color: #4b5563;">
                Best regards,<br>
                <strong style="font-weight: 600; color: #111827;">The SBIQ Team</strong>
              </p>
            </td>
          </tr>
          <tr>
            <td align="center" class="footer-padding" style="padding: 20px 30px; background-color: #f8fafc; border-top: 1px solid #e5e7eb; color: #94a3b8; font-size: 12px; line-height: 1.5;">
              <p style="margin: 0 0 6px 0;">&copy; 2026 SBIQ. All rights reserved.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _registration_received_text(*, first_name: str, email: str) -> str:
    return (
        f"Hello {first_name},\n\n"
        f"Thank you for signing up for SBIQ using {email}. Your request is now pending review by an administrator.\n"
        "You'll receive a separate email with your login credentials as soon as your account is approved.\n\n"
        "Best regards,\n"
        "The SBIQ Team"
    )


def _send_activation_email(smtp: SmtpMaster, *, to_email: str, subject: str, text_body: str, html_body: str) -> None:
    password = decrypt_credential(smtp.password_encrypted) if smtp.password_encrypted else None
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{smtp.from_name} <{smtp.from_email}>" if smtp.from_name else smtp.from_email
    message["To"] = to_email
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    timeout = 20
    if smtp.encryption_type == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=timeout, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(smtp.host, smtp.port, timeout=timeout)

    with client:
        client.ehlo()
        if smtp.encryption_type == "starttls":
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if smtp.username:
            if not password:
                raise ValueError("SMTP password is required for authentication")
            client.login(smtp.username, password)
        client.send_message(message)


async def _notify_registration_received(user: UserMaster, db: AsyncSession) -> None:
    """Best-effort confirmation email; failures are logged but never block registration."""
    subject = "We received your SBIQ registration request"
    html_body = _registration_received_html(first_name=user.first_name, email=user.email)
    text_body = _registration_received_text(first_name=user.first_name, email=user.email)

    log = EmailLog(receiver_user_id=user.id, subject=subject, body=html_body, status="pending")
    db.add(log)
    await db.flush()

    smtp = await _system_smtp(db)
    if smtp is None:
        log.status = "failed"
        log.error_message = "No active SMTP configuration available to send the registration email."
        await db.commit()
        return

    try:
        if is_microsoft_graph_mail_configured():
            await send_microsoft_graph_mail(
                from_email=smtp.from_email, to_email=user.email, subject=subject, html_body=html_body, reply_to_email=smtp.from_email
            )
        else:
            await asyncio.to_thread(
                _send_activation_email, smtp, to_email=user.email, subject=subject, text_body=text_body, html_body=html_body
            )
        log.status = "sent"
        log.sent_at = datetime.now(UTC)
    except (OSError, smtplib.SMTPException, ValueError, MicrosoftGraphMailError) as exc:
        log.status = "failed"
        log.error_message = str(exc)
    await db.commit()


@router.post("/public/register", response_model=RegistrationResponse)
async def register_user(payload: RegistrationRequest, db: AsyncSession = Depends(get_async_db)) -> RegistrationResponse:
    """Store a public website registration request in user_master."""
    email = payload.email.lower().strip()
    phone = payload.phone.strip()
    await _ensure_unique_contact(email, phone, db)

    role = await _user_role(db)
    first_name = payload.first_name.strip()
    last_name = (payload.last_name or "").strip() or None
    if not first_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="First name is required")
    user = UserMaster(
        first_name=first_name,
        last_name=last_name,
        email=email,
        mobile_phone=phone,
        company_name=(payload.company or "").strip() or None,
        registration_message=(payload.message or "").strip() or None,
        role_id=role.id,
        member_status="pending_confirmation",
        status="pending",
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account request already exists for this email address or phone number."
        ) from exc
    await db.refresh(user)

    await _notify_registration_received(user, db)

    return RegistrationResponse(
        success=True, message="Thank you for registering. Your account will be activated after organization confirmation."
    )


@router.post("/admin/registrations/{user_id}/activate", response_model=RegistrationDecisionResponse)
async def activate_registration(
    user_id: UUID, admin_user: UserMaster = Depends(current_admin), db: AsyncSession = Depends(get_async_db)
) -> RegistrationDecisionResponse:
    """Activate a pending registration and email the generated credentials."""
    await _ensure_super_admin(admin_user, db)
    user = await db.get(UserMaster, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    if user.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending registrations can be activated")

    smtp = await _active_smtp(admin_user.id, db)
    password = _generate_password()
    user.password_hash = hash_password(password)
    user.status = "active"
    user.member_status = "approved"
    user.approved_by = admin_user.id
    user.approved_at = datetime.now(UTC)

    subject = "Your SBIQ account has been activated"
    html_body = _activation_email_html(
        application_url=settings.MATCHMAKING_APPLICATION_URL, email=user.email, first_name=user.first_name, password=password
    )
    text_body = _activation_email_text(
        application_url=settings.MATCHMAKING_APPLICATION_URL, email=user.email, first_name=user.first_name, password=password
    )

    log = EmailLog(sender_user_id=admin_user.id, receiver_user_id=user.id, subject=subject, body=html_body, status="pending")
    db.add(log)
    await db.flush()

    try:
        if is_microsoft_graph_mail_configured():
            await send_microsoft_graph_mail(
                from_email=smtp.from_email, to_email=user.email, subject=subject, html_body=html_body, reply_to_email=smtp.from_email
            )
        else:
            await asyncio.to_thread(
                _send_activation_email, smtp, to_email=user.email, subject=subject, text_body=text_body, html_body=html_body
            )
    except (OSError, smtplib.SMTPException, ValueError, MicrosoftGraphMailError) as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Activation email failed: {exc}") from exc

    log.status = "sent"
    await db.commit()
    return RegistrationDecisionResponse(success=True, message="Registration activated and account email sent successfully.", user_id=user.id, status=user.status)


@router.post("/admin/registrations/{user_id}/reject", response_model=RegistrationDecisionResponse)
async def reject_registration(
    user_id: UUID, admin_user: UserMaster = Depends(current_admin), db: AsyncSession = Depends(get_async_db)
) -> RegistrationDecisionResponse:
    """Reject a pending registration."""
    await _ensure_super_admin(admin_user, db)
    user = await db.get(UserMaster, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    if user.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending registrations can be rejected")

    user.status = "rejected"
    user.member_status = "rejected"
    user.approved_by = admin_user.id
    user.approved_at = datetime.now(UTC)
    await db.commit()
    return RegistrationDecisionResponse(success=True, message="Registration rejected successfully.", user_id=user.id, status=user.status)
