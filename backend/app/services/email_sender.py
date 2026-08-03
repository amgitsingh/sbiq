from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import settings

# Port 465 is implicit TLS (SMTPS) — the connection must be SSL-wrapped from
# the first byte (smtplib.SMTP_SSL). 587/25 are plaintext-then-upgrade
# (STARTTLS). Mixing these up doesn't degrade gracefully: calling
# .starttls() over a port expecting implicit SSL just hangs/times out or
# errors, it doesn't silently fall back.
_IMPLICIT_TLS_PORT = 465


class EmailSendError(Exception):
    """Raised when SMTP configuration is missing or the send itself fails."""


def send_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
    from_display_name: str | None = None,
) -> None:
    """Send a plain-text email via SMTP (app.core.config settings).

    The `From` address is always SMTP_FROM_EMAIL, never a participant's real
    address — most mail servers reject or spam-flag a `From` outside the
    authenticated account's own domain (no SPF/DKIM for domains we don't
    control). "Sent by participant A" is instead conveyed via the display
    name plus `Reply-To` set to A's real address, so replies still land with
    A directly — the standard "on behalf of" email pattern.
    """
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        raise EmailSendError("SMTP is not configured (SMTP_HOST / SMTP_FROM_EMAIL missing)")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = (
        f'"{from_display_name}" <{settings.SMTP_FROM_EMAIL}>'
        if from_display_name
        else settings.SMTP_FROM_EMAIL
    )
    msg["To"] = to_email
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    try:
        smtp_cls = smtplib.SMTP_SSL if settings.SMTP_PORT == _IMPLICIT_TLS_PORT else smtplib.SMTP
        with smtp_cls(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            if settings.SMTP_USE_TLS and settings.SMTP_PORT != _IMPLICIT_TLS_PORT:
                server.starttls()
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise EmailSendError(str(e)) from e
