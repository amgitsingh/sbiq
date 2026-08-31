"""Compose the combined per-participant matches email
(docs/mail-template.docx) - one email, sent by the event organizer to a
participant, listing every one of their approved matches together.

Deliberately NOT LLM-generated: the header/footer/section labels are fixed
branded copy (event date/venue substituted in) that must stay consistent
across every send, not vary token-by-token per LLM call. Only the per-match
variable content - reasoning bullets, reciprocal_reason, linkedin_draft -
comes from the LLM (app/services/matching/llm_matcher.py), generated once at
matching time and stored on the Match row.

This is a new, additive email - distinct from the existing per-pair
"POST /{event_id}/matches/send-email" (app/routers/events.py::send_match_email),
which sends one participant's own outreach email_draft to their counterpart
and is unaffected by this module (protected by CLAUDE.md's Phase-1 exception).
"""
from __future__ import annotations

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


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else full_name


def _count_word(n: int, words: dict[int, str]) -> str:
    return words.get(n, str(n))


def _en_intro(event: Event, participant: Participant, match_count: int) -> str:
    organizer = settings.EMAIL_ORGANIZER_NAME
    when = f"On {event.date}, " if event.date else ""
    where = f" at {event.location}" if event.location else ""
    count_word = _count_word(match_count, _EN_COUNT_WORDS)
    plural = "es" if match_count != 1 else ""
    return (
        f"Dear {_first_name(participant.name)},\n\n"
        f"{when}we are looking forward to welcoming you to {event.name}{where}, "
        f"organised by {organizer}.\n\n"
        f"For this event, {organizer} is using SBIQ.ai for AI-powered Smart Business "
        f"Matching. The objective is simple: not to meet as many people as possible, "
        f"but to identify the people who are most commercially relevant to you.\n\n"
        f"We are pleased to have been able to create your personal matches based on "
        f"the information you provided yourself — including your expertise, business "
        f"interests, challenges and collaboration preferences — combined with relevant "
        f"information we could identify through public sources.\n\n"
        f"Based on this, we have selected the following {count_word} match{plural} we "
        f"believe you should meet during the event."
    )


def _en_match_block(match: Match, candidate: Participant, index: int, total: int) -> str:
    header = "Your SBIQ Business Match" + (f" ({index} of {total})" if total > 1 else "")
    company_line = f"{candidate.name} — {candidate.company}" if candidate.company else candidate.name
    lines = [header, "", company_line]
    if candidate.designation:
        lines.append(candidate.designation)
    lines += ["", "Why we believe you should meet:"]
    for label, bullet in zip(_EN_REASON_LABELS, match.reasoning or []):
        lines.append(f"{label} — {bullet}")
    lines += [
        "",
        f"Why you could be interesting to {_first_name(candidate.name)}:",
        match.reciprocal_reason or "",
        "",
        "This is therefore not simply a networking introduction. We see a specific "
        "potential business opportunity worth exploring.",
        "",
        "Connect beforehand on LinkedIn",
        f"You can already connect with {_first_name(candidate.name)} on LinkedIn. That "
        "makes it much easier to find each other and have a meaningful conversation "
        "during the event.",
        "",
        "LinkedIn introduction — copy & paste:",
        match.linkedin_draft or "",
    ]
    return "\n".join(lines)


def _en_footer(event: Event) -> str:
    organizer = settings.EMAIL_ORGANIZER_NAME
    when = f" We look forward to seeing you on {event.date}" if event.date else " We look forward to seeing you"
    where = f" at {event.location}" if event.location else ""
    return (
        f"Why {organizer} is doing this\n\n"
        f"With Smart Business Matching, {organizer} wants to create more measurable "
        f"value from its business network. SBIQ looks beyond job titles and industries "
        f"and identifies connections based on shared interests, complementary "
        f"expertise, business challenges, collaboration opportunities, potential "
        f"client–supplier relationships and strategic partnerships.\n\n"
        f"We hope this introduction helps you make the most of your time at "
        f"{event.name}.\n\n"
        f"{when}{where}.\n\n"
        f"Warm regards,\n"
        f"{organizer}\n"
        f"in collaboration with SBIQ.ai\n"
        f"Smart Business Matching — connecting the right people to create business "
        f"opportunities"
    )


def _nl_intro(event: Event, participant: Participant, match_count: int) -> str:
    organizer = settings.EMAIL_ORGANIZER_NAME
    when = f"Op {event.date} " if event.date else ""
    where = f" bij {event.location}" if event.location else ""
    count_word = _count_word(match_count, _NL_COUNT_WORDS)
    plural = "es" if match_count != 1 else ""
    return (
        f"Beste {_first_name(participant.name)},\n\n"
        f"{when}zien we je graag bij {event.name}{where}.\n\n"
        f"Voor dit event zet {organizer} opnieuw SBIQ.ai in voor Smart Business "
        f"Matching. Het doel is simpel: niet zoveel mogelijk mensen ontmoeten, maar "
        f"juist de mensen die voor jou zakelijk het meest relevant kunnen zijn.\n\n"
        f"Op basis van de informatie die je zelf bij je aanmelding hebt aangegeven — "
        f"zoals je expertise, uitdagingen, samenwerkingswensen en zakelijke "
        f"interesses — én informatie die we via openbare bronnen over de deelnemers "
        f"konden vinden, hebben we gekeken welke verbindingen het meest kansrijk "
        f"zijn.\n\n"
        f"We zijn blij dat we je voor het event onderstaande {count_word} match{plural} "
        f"kunnen meegeven."
    )


def _nl_match_block(match: Match, candidate: Participant, index: int, total: int) -> str:
    header = "Jouw SBIQ-match" + (f" ({index} van {total})" if total > 1 else "")
    company_line = f"{candidate.name} — {candidate.company}" if candidate.company else candidate.name
    lines = [header, "", company_line]
    if candidate.designation:
        lines.append(candidate.designation)
    lines += ["", "Waarom denken we dat jullie elkaar moeten spreken?"]
    for label, bullet in zip(_NL_REASON_LABELS, match.reasoning or []):
        lines.append(f"{label} — {bullet}")
    lines += [
        "",
        f"Waarom jij interessant bent voor {_first_name(candidate.name)}:",
        match.reciprocal_reason or "",
        "",
        "Dit is dus geen willekeurige netwerkintroductie. We zien specifiek een "
        "mogelijke business opportunity tussen jullie.",
        "",
        "Al vóór het event contact maken?",
        f"Je kunt via LinkedIn alvast een connectie leggen met {_first_name(candidate.name)}. "
        "Daarmee wordt het op het event een stuk makkelijker om elkaar daadwerkelijk "
        "op te zoeken.",
        "",
        "LinkedIn-introductie — kopieer & plak:",
        match.linkedin_draft or "",
    ]
    return "\n".join(lines)


def _nl_footer(event: Event) -> str:
    organizer = settings.EMAIL_ORGANIZER_NAME
    when = f" Graag tot {event.date}" if event.date else " Graag tot ziens"
    where = f" bij {event.location}" if event.location else ""
    return (
        f"Waarom we dit doen\n\n"
        f"Met Smart Business Matching wil {organizer} de waarde van het netwerk "
        f"verder vergroten. SBIQ.ai kijkt daarbij onder andere naar gedeelde "
        f"interesses, complementaire expertise, gezamenlijke uitdagingen, "
        f"potentiële samenwerkingen en concrete zakelijke kansen.\n\n"
        f"Zo proberen we van een netwerkbijeenkomst meer te maken dan alleen goede "
        f"gesprekken en nieuwe LinkedIn-connecties: gerichte introducties die "
        f"daadwerkelijk kunnen leiden tot klanten, partnerships, opdrachten of "
        f"andere zakelijke kansen.\n\n"
        f"{when}{where}.\n\n"
        f"Met ondernemende groet,\n"
        f"{organizer}\n"
        f"i.s.m. SBIQ.ai\n"
        f"Smart Business Matching — de juiste mensen ontmoeten."
    )


def compose_matches_email(
    event: Event,
    participant: Participant,
    matches: list[tuple[Match, Participant]],
    language: str | None,
) -> tuple[str, str]:
    """Build (subject, plain-text body) for one participant's combined
    matches email. `matches` is [(match row where match.participant_a_id ==
    participant.id, the matched candidate participant), ...], already
    filtered/ordered by the caller (app/routers/events.py::send_participant_matches).

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
        parts += [
            _nl_match_block(m, c, i, total) for i, (m, c) in enumerate(matches, start=1)
        ]
        parts.append(_nl_footer(event))
    else:
        subject = f"Your SBIQ matches for {event.name}"
        parts = [_en_intro(event, participant, total)]
        parts += [
            _en_match_block(m, c, i, total) for i, (m, c) in enumerate(matches, start=1)
        ]
        parts.append(_en_footer(event))

    return subject, "\n\n".join(parts)
