"""Compose the combined per-participant matches email - one email, sent by
the event organizer to a participant, listing every one of their approved
matches together.

Markup follows the client-approved reference template
(docs/sbiq_business_matches_email.html) exactly: a table-based layout
(`<table role="presentation">`, not divs/flex/grid), the one email-safe
technique that renders identically across Gmail, Outlook, and Apple Mail -
divs with modern CSS (flex/grid, box-shadow-only affordances) are
unreliable in several of those clients. Colors/fonts below are the
reference's own literal values, not re-derived from anything else.

The sbiq.ai logo is embedded via a Content-ID (cid:) reference, resolved by
app/services/email_sender.py's `inline_images` at real send time - NOT a
data: URI (the reference file's own approach) or a hosted URL. A data: URI
is stripped by Gmail and several other major clients; this app has no
public static-asset host to link to instead. CID embedding is the one
technique that reliably renders inline everywhere. Trade-off: the
`email_draft` *preview* field returned by GET endpoints is a bare HTML
string with no attachment behind it, so the logo shows as a broken image
in that preview context - only a real send (send_match_email/
send_participant_matches) carries the actual attached bytes. Acceptable
since the preview's job is reviewing the reasoning text, not pixel-perfect
rendering.

Deliberately NOT LLM-generated: the header/footer/section copy is fixed
branded text (event date/name substituted in) that must stay consistent
across every send, not vary token-by-token per LLM call. Only the per-match
variable content - reasoning bullets, reciprocal_reason, linkedin_draft -
comes from the LLM (app/services/matching/llm_matcher.py), generated once at
matching time and stored on the Match row. The 3 reasoning-bullet labels
below ("Stronger positioning" etc.) are also fixed copy, not LLM output -
only the sentence after each label's dash is LLM-generated; see
llm_matcher.SYSTEM_PROMPT for the underlying "exactly 3, fixed order, fixed
meaning" bullets these labels are wrapped around.

The "Your SBIQ Business Match(es) — and why you should meet" section header
is written ONCE for the whole matches section (not once per match) - each
match below is already its own visually distinct card. The CTA button
("View My Full Match Report") links to settings.MATCHMAKING_APPLICATION_URL
- there's no participant-facing match-report page yet (Phase 2, per
CLAUDE.md's Phase Boundaries), so this points at the general login page for
now rather than a dead "#" link; swap it once that page exists.

Also used by the per-pair "POST /{event_id}/matches/send-email"
(app/routers/events.py::send_match_email, protected by CLAUDE.md's Phase-1
exception) - same content/voice, just scoped to one match instead of every
approved match at once - and by GET /{event_id}/matches and
GET /{event_id}/participants/{id}/matches as a live "email_draft" preview
of what a real send would actually contain (compose_single_match_preview
below), since the LLM no longer generates a separate free-form email_draft
of its own (see llm_matcher.py's module docstring).
"""
from __future__ import annotations

import html
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.config import settings
from app.models.event import Event
from app.models.match import Match
from app.models.participant import Participant

# app/assets/logo-email.png - two levels up from this file (matching/ ->
# services/ -> app/), not relative to the process's cwd, so this resolves
# correctly regardless of where uvicorn/celery were launched from. Lives
# under app/, NOT the repo-root data/ directory - that whole directory is
# gitignored (real participant data dumps live there), so anything placed
# there never reaches a fresh `git pull` deploy. This is a real runtime
# dependency of every match email send, so it has to actually be tracked.
#
# A pre-composited PNG, not the source logo.webp (kept alongside it) -
# the source file has a transparent background, and several email clients
# (Outlook and some mobile Gmail renderers especially) don't handle WebP's
# alpha channel correctly and paint transparent pixels black instead of
# see-through. PNG alpha support is universal by comparison, so the fix is
# to flatten the transparency onto solid white ONCE (matching the white box
# it always sits in - see _header_row) and embed that instead, rather than
# ship a format whose transparency isn't reliably honored. Regenerate if the
# source logo changes: PIL composite onto an RGB white canvas using the
# alpha channel as the paste mask, saved as PNG - not committed as a build
# step (Pillow isn't a project dependency; this is a one-off asset, not a
# runtime conversion).
_LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "logo-email.png"
_logo_bytes_cache: bytes | None = None


def get_logo_inline_image() -> dict[str, tuple[bytes, str]]:
    """The real sbiq.ai logo, for email_sender.send_email's `inline_images`
    param - cached in memory after first read since the file is static.
    Referenced from the composed HTML below as <img src="cid:logo">."""
    global _logo_bytes_cache
    if _logo_bytes_cache is None:
        _logo_bytes_cache = _LOGO_PATH.read_bytes()
    return {"logo": (_logo_bytes_cache, "png")}


# Literal values from docs/sbiq_business_matches_email.html - not re-derived.
_NAVY = "#0b2a54"
_ORANGE = "#f4841f"
_PAGE_BG = "#eef1f5"
_CARD_BG = "#ffffff"
_TEXT_DARK = "#1c2b3a"
_TEXT_BODY = "#3a4a5c"
_TEXT_MUTED = "#5c6b7a"
_TEXT_FOOTER = "#8b97a6"
_TEXT_FOOTER_LIGHT = "#b0b9c4"
_MATCH_CARD_BG = "#f7f9fc"
_MATCH_CARD_BORDER = "#e6ecf3"
_CALLOUT_BG = "#fdf3e9"
_LINKEDIN_BORDER = "#d5deea"
_HEADER_DATE_COLOR = "#f4a24d"
_HEADER_DATE_SUB = "#c9d6e6"
_SANS = "Arial, Helvetica, sans-serif"
_SERIF = "Georgia, 'Times New Roman', serif"

# Fixed labels for the 3 reasoning bullets, per the client-approved
# template - only the label text, not the underlying "exactly 3, fixed
# order, fixed meaning" bullets themselves (llm_matcher.SYSTEM_PROMPT),
# which this only renames how each is introduced in the email.
_EN_REASON_LABELS = ("Stronger positioning", "Complementary expertise", "Business opportunity")
_NL_REASON_LABELS = ("Sterkere positionering", "Complementaire expertise", "Zakelijke kans")

_EN_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
_NL_COUNT_WORDS = {1: "één", 2: "twee", 3: "drie", 4: "vier", 5: "vijf"}


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else full_name


def _count_word(n: int, words: dict[int, str]) -> str:
    return words.get(n, str(n))


def _esc(text: str) -> str:
    return html.escape(text or "")


def _name_company_line(candidate: Participant) -> str:
    """'Name — Company' - the reference template drops designation from
    this line entirely (unlike an earlier draft), so it isn't included."""
    return f"{candidate.name} — {candidate.company}" if candidate.company else candidate.name


def _reason_rows(labels: tuple[str, str, str], reasoning: list[str]) -> str:
    """The 3 reasons as stacked 2-column table rows (orange dot + bold
    label + text) - the reference template's own bullet technique, more
    reliable across email clients (particularly Outlook) than native
    <ul>/<li> marker styling."""
    rows = []
    for label, text in zip(labels, reasoning):
        rows.append(
            '<tr>'
            f'<td style="padding:0 0 10px 0; vertical-align:top; width:20px;">'
            f'<span style="color:{_ORANGE}; font-size:15px;">&#9679;</span></td>'
            f'<td style="padding:0 0 10px 0; font-size:14px; line-height:1.6; color:{_TEXT_BODY};">'
            f'<strong style="color:{_NAVY};">{_esc(label)}</strong> &mdash; {_esc(text)}</td>'
            '</tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' + "".join(rows) + "</table>"
    )


def _match_card(
    candidate: Participant,
    match: Any,
    labels: tuple[str, str, str],
    why_interesting_label: str,
    connect_label: str,
    linkedin_eyebrow: str,
) -> str:
    """One match card - shared by EN/NL, only the 3 label strings differ."""
    return (
        '<tr><td style="padding:28px 40px 0 40px; font-family:'
        + _SANS
        + ';">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background-color:{_MATCH_CARD_BG}; border:1px solid {_MATCH_CARD_BORDER}; border-radius:8px;">'
        '<tr><td style="padding:22px 26px 6px 26px;">'
        f'<p style="margin:0 0 14px 0; font-size:17px; color:{_NAVY}; font-weight:bold; font-family:{_SERIF};">'
        f"{_esc(_name_company_line(candidate))}</p>"
        f"{_reason_rows(labels, match.reasoning or [])}"
        "</td></tr>"
        '<tr><td style="padding:6px 26px 22px 26px;">'
        f'<p style="margin:14px 0 6px 0; font-size:14px; color:{_NAVY}; font-weight:bold;">'
        f"{why_interesting_label} {_esc(_first_name(candidate.name))}</p>"
        f'<p style="margin:0 0 16px 0; font-size:14px; line-height:1.6; color:{_TEXT_BODY};">'
        f"{_esc(match.reciprocal_reason or '')}</p>"
        f'<p style="margin:0 0 10px 0; font-size:13px; line-height:1.5; color:{_TEXT_MUTED};">'
        f"{connect_label.format(name=_esc(_first_name(candidate.name)))}</p>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background-color:{_CARD_BG}; border:1px dashed {_LINKEDIN_BORDER}; border-radius:6px;">'
        '<tr><td style="padding:14px 18px;">'
        f'<p style="margin:0 0 6px 0; font-size:11px; letter-spacing:1px; text-transform:uppercase; '
        f'color:{_ORANGE}; font-weight:bold;">{linkedin_eyebrow}</p>'
        f'<p style="margin:0; font-size:13.5px; line-height:1.6; color:{_TEXT_BODY}; font-style:italic;">'
        f"“{_esc(match.linkedin_draft or '')}”</p>"
        "</td></tr></table>"
        "</td></tr></table>"
        "</td></tr>"
    )


def _header_row(event: Event, date_label: str) -> str:
    return (
        '<tr><td style="background-color:'
        + _NAVY
        + '; padding:28px 40px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        '<td align="left" valign="middle">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="background-color:{_CARD_BG}; '
        'border-radius:6px;"><tr><td style="padding:8px 14px;">'
        '<img src="cid:logo" alt="sbiq.ai" width="120" style="display:block; border:0;"></td></tr></table>'
        "</td>"
        f'<td align="right" valign="middle" style="font-family:{_SANS}; color:{_HEADER_DATE_COLOR}; '
        f'font-size:12px; letter-spacing:2px; text-transform:uppercase;">'
        f'{_esc(event.name).upper()}<br>'
        f'<span style="color:{_HEADER_DATE_SUB}; letter-spacing:1px;">{_esc(date_label).upper()}</span></td>'
        "</tr></table>"
        "</td></tr>"
        f'<tr><td style="height:5px; line-height:5px; font-size:0; background-color:{_ORANGE}; '
        f'background:linear-gradient(90deg, {_NAVY} 0%, {_ORANGE} 100%);">&nbsp;</td></tr>'
    )


def _cta_row(label: str) -> str:
    url = settings.MATCHMAKING_APPLICATION_URL
    return (
        '<tr><td style="padding:32px 40px 8px 40px;" align="center">'
        '<table role="presentation" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="border-radius:6px; background-color:{_ORANGE};">'
        f'<a href="{_esc(url)}" style="display:inline-block; padding:14px 36px; font-family:{_SANS}; '
        f'font-size:14px; font-weight:bold; color:#ffffff; text-decoration:none; border-radius:6px;">'
        f"{_esc(label)}</a></td></tr></table>"
        "</td></tr>"
    )


def _en_intro_row(event: Event, participant: Participant, match_count: int) -> str:
    when = f"On <strong>{_esc(event.date)}</strong>, " if event.date else ""
    connection = (
        "a highly relevant business connection"
        if match_count == 1
        else f"{_count_word(match_count, _EN_COUNT_WORDS)} highly relevant business connections"
    )
    noun = "Match" if match_count == 1 else "Matches"
    return (
        '<tr><td style="padding:36px 40px 8px 40px; font-family:'
        + _SANS
        + f'; color:{_TEXT_DARK};">'
        f'<p style="margin:0 0 16px 0; font-size:16px; line-height:1.6;">Dear {_esc(_first_name(participant.name))},</p>'
        f'<p style="margin:0 0 16px 0; font-size:15px; line-height:1.7; color:{_TEXT_BODY};">'
        f"{when}we look forward to welcoming you to <strong>{_esc(event.name)}</strong>, organised by "
        f"<strong>{_esc(settings.EMAIL_ORGANIZER_NAME)}</strong>.</p>"
        f'<p style="margin:0 0 16px 0; font-size:15px; line-height:1.7; color:{_TEXT_BODY};">'
        f"For this event, we are using <strong>SBIQ.ai</strong> for AI-powered Smart Business Matching.</p>"
        f'<p style="margin:0 0 20px 0; font-size:15px; line-height:1.7; color:{_TEXT_BODY};">'
        f"Based on the information you provided about your expertise, business interests and ambitions, "
        f"combined with relevant publicly available information, SBIQ has identified {connection} for "
        f"you.</p>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px 0;">'
        f'<tr><td style="background-color:{_CALLOUT_BG}; border-left:4px solid {_ORANGE}; padding:16px 20px; '
        'border-radius:4px;">'
        f'<p style="margin:0; font-size:15px; line-height:1.6; color:{_NAVY}; font-weight:bold;">'
        "The goal is simple: not to meet as many people as possible, but to meet the right people.</p>"
        "</td></tr></table>"
        f'<h2 style="margin:0 0 6px 0; font-family:{_SERIF}; font-size:19px; color:{_NAVY}; '
        f'border-bottom:2px solid {_MATCH_CARD_BORDER}; padding-bottom:14px;">'
        f"Your SBIQ Business {noun} &mdash; and why you should meet</h2>"
        "</td></tr>"
    )


def _en_footer_row(event: Event) -> str:
    return (
        '<tr><td style="padding:32px 40px 36px 40px; font-family:'
        + _SANS
        + ';">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-top:1px solid {_MATCH_CARD_BORDER}; padding-top:20px;">'
        '<tr><td style="padding-top:20px;" align="center">'
        f'<p style="margin:0; font-size:12px; color:{_TEXT_FOOTER}; line-height:1.6;">'
        f"Smart Business Matching for {_esc(settings.EMAIL_ORGANIZER_NAME)} &mdash; {_esc(event.name)}"
        + (f", {_esc(event.date)}" if event.date else "")
        + "</p>"
        f'<p style="margin:8px 0 0 0; font-size:11px; color:{_TEXT_FOOTER_LIGHT};">'
        f"You are receiving this email because you registered for {_esc(event.name)}.</p>"
        "</td></tr></table>"
        "</td></tr>"
    )


def _nl_intro_row(event: Event, participant: Participant, match_count: int) -> str:
    when = f"Op <strong>{_esc(event.date)}</strong> " if event.date else ""
    connection = (
        "een voor jou zeer relevante zakelijke connectie"
        if match_count == 1
        else f"{_count_word(match_count, _NL_COUNT_WORDS)} voor jou zeer relevante zakelijke connecties"
    )
    noun = "Match" if match_count == 1 else "Matches"
    return (
        '<tr><td style="padding:36px 40px 8px 40px; font-family:'
        + _SANS
        + f'; color:{_TEXT_DARK};">'
        f'<p style="margin:0 0 16px 0; font-size:16px; line-height:1.6;">Beste {_esc(_first_name(participant.name))},</p>'
        f'<p style="margin:0 0 16px 0; font-size:15px; line-height:1.7; color:{_TEXT_BODY};">'
        f"{when}kijken we ernaar uit je te verwelkomen bij <strong>{_esc(event.name)}</strong>, "
        f"georganiseerd door <strong>{_esc(settings.EMAIL_ORGANIZER_NAME)}</strong>.</p>"
        f'<p style="margin:0 0 16px 0; font-size:15px; line-height:1.7; color:{_TEXT_BODY};">'
        f"Voor dit event zetten we <strong>SBIQ.ai</strong> in voor AI-gedreven Smart Business Matching.</p>"
        f'<p style="margin:0 0 20px 0; font-size:15px; line-height:1.7; color:{_TEXT_BODY};">'
        f"Op basis van de informatie die je hebt gegeven over jouw expertise, zakelijke interesses en "
        f"ambities, aangevuld met relevante informatie uit openbare bronnen, heeft SBIQ {connection} "
        f"geïdentificeerd.</p>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px 0;">'
        f'<tr><td style="background-color:{_CALLOUT_BG}; border-left:4px solid {_ORANGE}; padding:16px 20px; '
        'border-radius:4px;">'
        f'<p style="margin:0; font-size:15px; line-height:1.6; color:{_NAVY}; font-weight:bold;">'
        "Het doel is simpel: niet zoveel mogelijk mensen ontmoeten, maar de juiste mensen.</p>"
        "</td></tr></table>"
        f'<h2 style="margin:0 0 6px 0; font-family:{_SERIF}; font-size:19px; color:{_NAVY}; '
        f'border-bottom:2px solid {_MATCH_CARD_BORDER}; padding-bottom:14px;">'
        f"Jouw SBIQ Business {noun} &mdash; en waarom jullie elkaar zouden moeten spreken</h2>"
        "</td></tr>"
    )


def _nl_footer_row(event: Event) -> str:
    return (
        '<tr><td style="padding:32px 40px 36px 40px; font-family:'
        + _SANS
        + ';">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-top:1px solid {_MATCH_CARD_BORDER}; padding-top:20px;">'
        '<tr><td style="padding-top:20px;" align="center">'
        f'<p style="margin:0; font-size:12px; color:{_TEXT_FOOTER}; line-height:1.6;">'
        f"Smart Business Matching voor {_esc(settings.EMAIL_ORGANIZER_NAME)} &mdash; {_esc(event.name)}"
        + (f", {_esc(event.date)}" if event.date else "")
        + "</p>"
        f'<p style="margin:8px 0 0 0; font-size:11px; color:{_TEXT_FOOTER_LIGHT};">'
        f"Je ontvangt deze e-mail omdat je bent aangemeld voor {_esc(event.name)}.</p>"
        "</td></tr></table>"
        "</td></tr>"
    )


def compose_matches_email(
    event: Event,
    participant: Participant,
    matches: list[tuple[Any, Participant]],
    language: str | None,
) -> tuple[str, str]:
    """Build (subject, HTML body) for one participant's combined matches
    email. `matches` is [(match content, the matched candidate participant),
    ...], already filtered/ordered by the caller
    (app/routers/events.py::send_participant_matches). "match content" is
    normally a real `Match` row, but any object exposing the same
    `.reasoning`/`.reciprocal_reason`/`.linkedin_draft` attributes works
    (compose_single_match_preview below passes a plain SimpleNamespace when
    previewing translated content, without mutating the real ORM row).

    The returned body is a full standalone HTML document (table-based
    layout, per docs/sbiq_business_matches_email.html) -
    app/services/email_sender.py derives the plain-text multipart/
    alternative part automatically, so callers never need a separate
    plain-text version of their own.

    language: event.content_language ("en"/"nl"/None) - same generation-time
    convention as everywhere else (llm_matcher, llm_normalizer), not a
    per-request toggle. The embedded reasoning/reciprocal_reason/
    linkedin_draft were already generated in this same language at matching
    time, so this only needs to pick which fixed template text to wrap them
    in - never re-translates the LLM content itself.
    """
    total = len(matches)
    date_label = event.date or event.name

    if language == "nl":
        subject = f"Jouw SBIQ Business Match{'es' if total != 1 else ''} voor {event.name}"
        rows = [
            _header_row(event, date_label),
            _nl_intro_row(event, participant, total),
        ]
        rows += [
            _match_card(
                c,
                m,
                _NL_REASON_LABELS,
                "Waarom jij interessant kunt zijn voor",
                "We raden je aan om vooraf alvast met {name} te connecten via LinkedIn "
                "&mdash; zo is het tijdens het event makkelijker om elkaar te vinden en heb "
                "je alvast een mooie basis voor het gesprek.",
                "KANT-EN-KLARE LINKEDIN-INTRODUCTIE",
            )
            for m, c in matches
        ]
        rows.append(_cta_row("Bekijk mijn volledige matchrapport"))
        rows.append(_nl_footer_row(event))
    else:
        subject = f"Your SBIQ Business Match{'es' if total != 1 else ''} for {event.name}"
        rows = [
            _header_row(event, date_label),
            _en_intro_row(event, participant, total),
        ]
        rows += [
            _match_card(
                c,
                m,
                _EN_REASON_LABELS,
                "Why you could be interesting to",
                "We recommend connecting with {name} on LinkedIn beforehand &mdash; it makes "
                "it easier to find each other at the event and gives you a head start on the "
                "conversation.",
                "READY-TO-USE LINKEDIN INTRODUCTION",
            )
            for m, c in matches
        ]
        rows.append(_cta_row("View My Full Match Report"))
        rows.append(_en_footer_row(event))

    body = (
        "<!DOCTYPE html>"
        f'<html lang="{language or "en"}" xmlns="http://www.w3.org/1999/xhtml"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{_esc(subject)}</title></head>"
        f'<body style="margin:0; padding:0; background-color:{_PAGE_BG}; font-family:{_SERIF};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background-color:{_PAGE_BG}; padding:32px 0;"><tr><td align="center">'
        '<table role="presentation" width="640" cellpadding="0" cellspacing="0" '
        f'style="background-color:{_CARD_BG}; border-radius:10px; overflow:hidden; '
        'box-shadow:0 4px 18px rgba(15,42,84,0.08);">' + "".join(rows) + "</table>"
        "</td></tr></table></body></html>"
    )
    return subject, body


def compose_single_match_preview(
    event: Event,
    recipient: Participant,
    match: Match,
    candidate: Participant,
    language: str | None,
    *,
    reasoning: list[str] | None = None,
    reciprocal_reason: str | None = None,
    linkedin_draft: str | None = None,
) -> str | None:
    """Preview text for exactly what POST /{event_id}/matches/send-email
    would actually send for this one match pair - the body returned by
    GET /{event_id}/matches as `email_draft`, so a caller previewing a match
    sees the real email, not stale/unused LLM-authored prose (see
    app/services/matching/llm_matcher.py's module docstring - the LLM no
    longer generates a free-form email_draft at all; this preview is built
    the same way the real send is).

    reasoning/reciprocal_reason/linkedin_draft: optional overrides - used by
    GET /{event_id}/participants/{id}/matches' `?lang=` on-demand
    translation to preview the *translated* email without writing translated
    text back onto the real Match row (a plain SimpleNamespace duck-typing
    Match's 3 relevant attributes is passed to compose_matches_email instead
    of the row itself). Defaults to the row's own native-language content
    when omitted.

    Returns None if the effective content is missing (the auto-received/
    mirror side of a bidirectional match never has real reasoning/
    reciprocal_reason/linkedin_draft) - same guard send_match_email itself
    enforces before allowing a real send.
    """
    effective_reasoning = reasoning if reasoning is not None else match.reasoning
    effective_reciprocal_reason = reciprocal_reason if reciprocal_reason is not None else match.reciprocal_reason
    effective_linkedin_draft = linkedin_draft if linkedin_draft is not None else match.linkedin_draft
    if not effective_reasoning or not effective_reciprocal_reason or not effective_linkedin_draft:
        return None

    content = SimpleNamespace(
        reasoning=effective_reasoning,
        reciprocal_reason=effective_reciprocal_reason,
        linkedin_draft=effective_linkedin_draft,
    )
    _subject, body = compose_matches_email(event, recipient, [(content, candidate)], language)
    return body
