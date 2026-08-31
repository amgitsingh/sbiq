"""Compose the combined per-participant matches email
(docs/mail-template.docx) - one email, sent by the event organizer to a
participant, listing every one of their approved matches together, as HTML
(matching the docx template's bold section headers/labels) with a plain-text
fallback derived automatically at send time (app/services/email_sender.py).

Deliberately NOT LLM-generated: the header/footer/section labels are fixed
branded copy (event date/venue substituted in) that must stay consistent
across every send, not vary token-by-token per LLM call. Only the per-match
variable content - reasoning bullets, reciprocal_reason, linkedin_draft -
comes from the LLM (app/services/matching/llm_matcher.py), generated once at
matching time and stored on the Match row.

Bold formatting mirrors the docx template's *consistent* structural pattern
- section headers, the "Name — Company" line, and the 3 reason labels
(Commercial/Complementary/Strategic opportunity, or Reden 1/2/3) are bold
everywhere they occur in the template. The docx's ad hoc word-level emphasis
inside filler prose (e.g. a specific date or venue name bolded in one
example sentence) isn't replicated - that's inconsistent, example-only
highlighting in that one sample event, not a rule that generalizes across
arbitrary event names/dates.

Kept deliberately concise, since email length scales with match count (a
Sponsor can have up to 3): each match block only includes what's
personalized to that match (reasoning + reciprocal_reason + LinkedIn draft)
- the generic "connect on LinkedIn beforehand" explanation and the "this
isn't just a networking intro" framing, both fixed boilerplate in the
original per-match template, are stated once in the intro instead of once
per match. The closing "why we do this" explainer section is dropped in
favour of a short sign-off once a participant has more than
_FULL_FOOTER_MAX_MATCHES matches, so a 3-match Sponsor email doesn't
compound 3x the per-match content with a long explanatory footer too.

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
from types import SimpleNamespace
from typing import Any

from app.core.config import settings
from app.models.event import Event
from app.models.match import Match
from app.models.participant import Participant

# English fixed labels for the 3 reasoning bullets, matching
# llm_matcher.SYSTEM_PROMPT's fixed bullet order exactly.
_EN_REASON_LABELS = ("Commercial opportunity", "Complementary expertise", "Strategic opportunity")
# Dutch template uses generic "Reden 1/2/3", not named categories.
_NL_REASON_LABELS = ("Reden 1", "Reden 2", "Reden 3")

_EN_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
_NL_COUNT_WORDS = {1: "één", 2: "twee", 3: "drie", 4: "vier", 5: "vijf"}

# Above this many matches, the long "why {organizer} is doing this"
# explainer paragraph is dropped in favour of a short sign-off - it's fixed
# boilerplate carrying no per-match information, so it's the first thing to
# trim once the per-match content alone already makes for a longer email.
_FULL_FOOTER_MAX_MATCHES = 2


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else full_name


def _count_word(n: int, words: dict[int, str]) -> str:
    return words.get(n, str(n))


def _esc(text: str) -> str:
    """Escape for HTML, preserving embedded newlines as <br> - LLM-generated
    reasoning/reciprocal_reason/linkedin_draft text is plain, not HTML."""
    return html.escape(text).replace("\n", "<br>")


def _p(inner_html: str) -> str:
    return f"<p>{inner_html}</p>"


def _bold_p(text: str) -> str:
    return f"<p><strong>{_esc(text)}</strong></p>"


def _label_p(label: str, text: str) -> str:
    """One paragraph with a bold leading label, e.g. 'Commercial
    opportunity — ...' with only the label bold - matches the docx's own
    bold-label/plain-body pattern for the 3 reasoning bullets."""
    return f"<p><strong>{_esc(label)}</strong> — {_esc(text)}</p>"


def _en_intro(event: Event, participant: Participant, match_count: int) -> str:
    organizer = settings.EMAIL_ORGANIZER_NAME
    when = f"On {event.date}, " if event.date else ""
    where = f" at {event.location}" if event.location else ""
    count_word = _count_word(match_count, _EN_COUNT_WORDS)
    plural = "es" if match_count != 1 else ""
    parts = [
        _p(f"Dear {_esc(_first_name(participant.name))},"),
        _p(
            f"{when}we are looking forward to welcoming you to {_esc(event.name)}{where}, "
            f"organised by {_esc(organizer)}."
        ),
        _p(
            f"For this event, {_esc(organizer)} is using SBIQ.ai for AI-powered Smart Business "
            f"Matching. The objective is simple: not to meet as many people as possible, "
            f"but to identify the people who are most commercially relevant to you."
        ),
        _p(
            f"We are pleased to have been able to create your personal matches based on "
            f"the information you provided yourself — including your expertise, business "
            f"interests, challenges and collaboration preferences — combined with relevant "
            f"information we could identify through public sources."
        ),
        _p(
            f"Based on this, we have selected the following {count_word} match{plural} we "
            f"believe you should meet during the event. This is not simply a networking "
            f"introduction — we see a specific potential business opportunity in each one. "
            f"For each match below you'll find why we believe you should meet, plus a "
            f"ready-to-use LinkedIn introduction — feel free to connect beforehand, it "
            f"makes it much easier to find each other at the event."
        ),
    ]
    return "\n".join(parts)


def _en_match_block(match: Any, candidate: Participant, index: int, total: int) -> str:
    header = "Your SBIQ Business Match" + (f" ({index} of {total})" if total > 1 else "")
    company_line = f"{candidate.name} — {candidate.company}" if candidate.company else candidate.name
    parts = [_bold_p(header), _bold_p(company_line)]
    if candidate.designation:
        parts.append(_p(_esc(candidate.designation)))
    parts.append(_bold_p("Why we believe you should meet:"))
    for label, bullet in zip(_EN_REASON_LABELS, match.reasoning or []):
        parts.append(_label_p(label, bullet))
    parts.append(_bold_p(f"Why you could be interesting to {_first_name(candidate.name)}:"))
    parts.append(_p(_esc(match.reciprocal_reason or "")))
    parts.append(_bold_p("LinkedIn introduction — copy & paste:"))
    parts.append(_p(_esc(match.linkedin_draft or "")))
    return "\n".join(parts)


def _en_footer(event: Event, match_count: int) -> str:
    organizer = settings.EMAIL_ORGANIZER_NAME
    sign_off = _p(f"Warm regards,<br>{_esc(organizer)}<br>in collaboration with SBIQ.ai")
    if match_count > _FULL_FOOTER_MAX_MATCHES:
        return sign_off

    when = f" We look forward to seeing you on {event.date}" if event.date else " We look forward to seeing you"
    where = f" at {event.location}" if event.location else ""
    explainer = _p(
        f"With Smart Business Matching, {_esc(organizer)} wants to create more measurable "
        f"value from its business network. SBIQ looks beyond job titles and industries "
        f"and identifies connections based on shared interests, complementary "
        f"expertise, business challenges, collaboration opportunities, potential "
        f"client–supplier relationships and strategic partnerships."
    )
    closing = _p(
        f"We hope this introduction helps you make the most of your time at "
        f"{_esc(event.name)}.{when}{where}."
    )
    return "\n".join([_bold_p(f"Why {organizer} is doing this"), explainer, closing, sign_off])


def _nl_intro(event: Event, participant: Participant, match_count: int) -> str:
    organizer = settings.EMAIL_ORGANIZER_NAME
    when = f"Op {event.date} " if event.date else ""
    where = f" bij {event.location}" if event.location else ""
    count_word = _count_word(match_count, _NL_COUNT_WORDS)
    plural = "es" if match_count != 1 else ""
    parts = [
        _p(f"Beste {_esc(_first_name(participant.name))},"),
        _p(f"{when}zien we je graag bij {_esc(event.name)}{where}."),
        _p(
            f"Voor dit event zet {_esc(organizer)} opnieuw SBIQ.ai in voor Smart Business "
            f"Matching. Het doel is simpel: niet zoveel mogelijk mensen ontmoeten, maar "
            f"juist de mensen die voor jou zakelijk het meest relevant kunnen zijn."
        ),
        _p(
            f"Op basis van de informatie die je zelf bij je aanmelding hebt aangegeven — "
            f"zoals je expertise, uitdagingen, samenwerkingswensen en zakelijke "
            f"interesses — én informatie die we via openbare bronnen over de deelnemers "
            f"konden vinden, hebben we gekeken welke verbindingen het meest kansrijk "
            f"zijn."
        ),
        _p(
            f"We zijn blij dat we je voor het event onderstaande {count_word} match{plural} "
            f"kunnen meegeven. Dit is dus geen willekeurige netwerkintroductie — we zien "
            f"specifiek een mogelijke business opportunity bij elke match. Je vindt "
            f"hieronder per match waarom we denken dat jullie elkaar moeten spreken, plus "
            f"een kant-en-klare LinkedIn-introductie — leg gerust alvast een connectie, dat "
            f"maakt het op het event een stuk makkelijker om elkaar te vinden."
        ),
    ]
    return "\n".join(parts)


def _nl_match_block(match: Any, candidate: Participant, index: int, total: int) -> str:
    header = "Jouw SBIQ-match" + (f" ({index} van {total})" if total > 1 else "")
    company_line = f"{candidate.name} — {candidate.company}" if candidate.company else candidate.name
    parts = [_bold_p(header), _bold_p(company_line)]
    if candidate.designation:
        parts.append(_p(_esc(candidate.designation)))
    parts.append(_bold_p("Waarom denken we dat jullie elkaar moeten spreken?"))
    for label, bullet in zip(_NL_REASON_LABELS, match.reasoning or []):
        parts.append(_label_p(label, bullet))
    parts.append(_bold_p(f"Waarom jij interessant bent voor {_first_name(candidate.name)}:"))
    parts.append(_p(_esc(match.reciprocal_reason or "")))
    parts.append(_bold_p("LinkedIn-introductie — kopieer & plak:"))
    parts.append(_p(_esc(match.linkedin_draft or "")))
    return "\n".join(parts)


def _nl_footer(event: Event, match_count: int) -> str:
    organizer = settings.EMAIL_ORGANIZER_NAME
    sign_off = _p(f"Met ondernemende groet,<br>{_esc(organizer)}<br>i.s.m. SBIQ.ai")
    if match_count > _FULL_FOOTER_MAX_MATCHES:
        return sign_off

    when = f" Graag tot {event.date}" if event.date else " Graag tot ziens"
    where = f" bij {event.location}" if event.location else ""
    explainer = _p(
        f"Met Smart Business Matching wil {_esc(organizer)} de waarde van het netwerk "
        f"verder vergroten. SBIQ.ai kijkt daarbij onder andere naar gedeelde "
        f"interesses, complementaire expertise, gezamenlijke uitdagingen, "
        f"potentiële samenwerkingen en concrete zakelijke kansen."
    )
    closing = _p(f"{when}{where}.")
    return "\n".join([_bold_p("Waarom we dit doen"), explainer, closing, sign_off])


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

    The returned body is HTML (bold section headers/labels/name-company
    line, per the docx template) - app/services/email_sender.py derives the
    plain-text multipart/alternative part automatically, so callers never
    need a separate plain-text version of their own.

    language: event.content_language ("en"/"nl"/None) - same generation-time
    convention as everywhere else (llm_matcher, llm_normalizer), not a
    per-request toggle. The embedded reasoning/reciprocal_reason/
    linkedin_draft were already generated in this same language at matching
    time, so this only needs to pick which fixed template text to wrap them
    in - never re-translates the LLM content itself.
    """
    total = len(matches)
    if language == "nl":
        subject = f"Jouw SBIQ-matches voor {event.name}"
        parts = [_nl_intro(event, participant, total)]
        parts += [_nl_match_block(m, c, i, total) for i, (m, c) in enumerate(matches, start=1)]
        parts.append(_nl_footer(event, total))
    else:
        subject = f"Your SBIQ matches for {event.name}"
        parts = [_en_intro(event, participant, total)]
        parts += [_en_match_block(m, c, i, total) for i, (m, c) in enumerate(matches, start=1)]
        parts.append(_en_footer(event, total))

    return subject, "\n".join(parts)


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
