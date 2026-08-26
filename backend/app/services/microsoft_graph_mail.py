"""Microsoft Graph mail delivery helpers.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\lib\\microsoft_graph_mail.py)
as part of docs/PLAN.md Phase 8 (Task 57). Reads the module-level `settings`
singleton directly (this repo's convention - see app/services/email_sender.py)
instead of IndMatchmaking's `Depends(get_settings)` pattern.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings

GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class MicrosoftGraphMailError(RuntimeError):
    """Raised when Microsoft Graph rejects auth or mail delivery."""


def is_microsoft_graph_mail_configured() -> bool:
    """Return whether all settings required for app-only Graph mail are present."""
    return bool(
        settings.MICROSOFT_GRAPH_TENANT_ID and settings.MICROSOFT_GRAPH_CLIENT_ID and settings.MICROSOFT_GRAPH_CLIENT_SECRET
    )


def _graph_error(prefix: str, response: httpx.Response) -> MicrosoftGraphMailError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    message = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
    if not message:
        message = response.text[:500] or response.reason_phrase
    return MicrosoftGraphMailError(f"{prefix} failed ({response.status_code}): {message}")


async def get_microsoft_graph_access_token() -> str:
    """Fetch a Microsoft Graph app-only access token using client credentials."""
    tenant_id = settings.MICROSOFT_GRAPH_TENANT_ID
    client_id = settings.MICROSOFT_GRAPH_CLIENT_ID
    client_secret = settings.MICROSOFT_GRAPH_CLIENT_SECRET
    if not tenant_id or not client_id or not client_secret:
        raise MicrosoftGraphMailError("Microsoft Graph mail credentials are not configured")

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    form = {
        "client_id": client_id,
        "client_secret": client_secret.get_secret_value(),
        "grant_type": "client_credentials",
        "scope": GRAPH_SCOPE,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.MICROSOFT_GRAPH_TIMEOUT_SECONDS) as client:
            response = await client.post(token_url, data=form)
    except httpx.HTTPError as exc:
        raise MicrosoftGraphMailError(f"Microsoft Graph token request failed: {exc}") from exc
    if response.status_code >= 400:
        raise _graph_error("Microsoft Graph token request", response)

    payload = response.json()
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise MicrosoftGraphMailError("Microsoft Graph token response did not include an access token")
    return access_token


async def send_microsoft_graph_mail(
    *,
    from_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    reply_to_email: str | None = None,
) -> None:
    """Send an HTML email through Microsoft Graph using app-only Mail.Send."""
    token = await get_microsoft_graph_access_token()
    message: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_body},
        "toRecipients": [{"emailAddress": {"address": to_email}}],
    }
    if reply_to_email:
        message["replyTo"] = [{"emailAddress": {"address": reply_to_email}}]

    sender = quote(from_email, safe="")
    url = f"{GRAPH_BASE_URL}/users/{sender}/sendMail"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"message": message, "saveToSentItems": True}
    try:
        async with httpx.AsyncClient(timeout=settings.MICROSOFT_GRAPH_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise MicrosoftGraphMailError(f"Microsoft Graph sendMail request failed: {exc}") from exc
    if response.status_code >= 400:
        raise _graph_error("Microsoft Graph sendMail request", response)
