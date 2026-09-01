from __future__ import annotations

import html as html_module
import re
import smtplib
from email.message import EmailMessage

from app.core.config import settings

# Port 465 is implicit TLS (SMTPS) — the connection must be SSL-wrapped from
# the first byte (smtplib.SMTP_SSL). 587/25 are plaintext-then-upgrade
# (STARTTLS). Mixing these up doesn't degrade gracefully: calling
# .starttls() over a port expecting implicit SSL just hangs/times out or
# errors, it doesn't silently fall back.
_IMPLICIT_TLS_PORT = 465

_TAG_RE = re.compile(r"<[^>]+>")


class EmailSendError(Exception):
    """Raised when SMTP configuration is missing or the send itself fails."""


def _html_to_plain(html_body: str) -> str:
    """Derive a plain-text fallback from the controlled <p>/<strong>/<br>
    markup participant_email_composer.py produces - good enough since the
    input is always our own simple, attribute-free markup, not arbitrary
    HTML. Used for the multipart/alternative's plain part (required for
    deliverability - an HTML-only email is more likely to be spam-flagged),
    never shown to a user on its own.
    """
    text = html_body.replace("<br>", "\n").replace("</p>", "\n\n")
    text = _TAG_RE.sub("", text)
    return html_module.unescape(text).strip()


def send_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    reply_to: str | None = None,
    from_display_name: str | None = None,
    inline_images: dict[str, tuple[bytes, str]] | None = None,
) -> None:
    """Send an HTML email via SMTP (app.core.config settings), with a plain-
    text fallback derived automatically for the multipart/alternative.

    The `From` address is always SMTP_FROM_EMAIL, never a participant's real
    address — most mail servers reject or spam-flag a `From` outside the
    authenticated account's own domain (no SPF/DKIM for domains we don't
    control). "Sent by participant A" is instead conveyed via the display
    name plus `Reply-To` set to A's real address, so replies still land with
    A directly — the standard "on behalf of" email pattern.

    inline_images: {cid: (raw_bytes, image_subtype)} - embedded via
    add_related (RFC 2392 Content-ID references), NOT a hosted URL or a
    data: URI. A hosted URL would need public asset hosting this app
    doesn't have; a data: URI is stripped by Gmail and several other major
    clients. CID embedding is the one technique that reliably renders
    inline in Gmail, Outlook, and Apple Mail alike. Reference from
    html_body as `<img src="cid:{cid}">` - the cid must match a key here
    exactly (no angle brackets in either place).
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
    msg.set_content(_html_to_plain(html_body))
    msg.add_alternative(html_body, subtype="html")

    if inline_images:
        # add_related on the html part nests it inside a multipart/related
        # container the way MUAs expect a cid-referenced image to arrive -
        # attaching it directly to `msg` instead would leave it a sibling
        # of the html part, not related to it, and most clients would then
        # show it as a plain attachment rather than resolving the cid: ref.
        html_part = msg.get_payload()[1]
        for cid, (data, subtype) in inline_images.items():
            html_part.add_related(data, maintype="image", subtype=subtype, cid=f"<{cid}>")

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
