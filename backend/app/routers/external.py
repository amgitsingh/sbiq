"""External API routes, reading QBCals' own data directly.

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\external\\controller.py)
as part of docs/PLAN.md Phase 8 (Task 61). Repointed: the source version
called `app.domain.studio.service` (an HTTP proxy to this very app, from
before the merge) - these routes now query QBCals' own `Event`/`Participant`
models directly. Fully sync (no `async def`/threadpool bridge needed) since
nothing here touches the async (UserMaster/RBAC) side of the schema at all -
`verify_external_api_key` is a plain header/settings comparison, no I/O.

Deliberately un-scoped by owner (unlike app/routers/events.py's Task 59
enforcement) - this is a system-to-system integration point gated by a
shared API key, not a per-user session, so it sees every event regardless
of who owns it, matching its original design.
"""

from __future__ import annotations

import csv
import io
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.event import Event
from app.models.participant import Participant

CSV_FIELDNAMES: tuple[str, ...] = (
    "id",
    "first_name",
    "last_name",
    "email",
    "company",
    "membership_tier",
    "enrichment_status",
    "participant_status",
)


def verify_external_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Enforce X-API-Key when EXTERNAL_API_KEY is configured; open otherwise."""
    if not settings.EXTERNAL_API_KEY:
        return
    expected = settings.EXTERNAL_API_KEY.get_secret_value()
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")


router = APIRouter(prefix="/external", tags=["external"], dependencies=[Depends(verify_external_api_key)])


class ExternalEventRead(BaseModel):
    id: int
    name: str
    date: str | None = None
    description: str | None = None
    status: str
    agenda: str | None = None
    matching_goals: str | None = None
    target_sectors: list[str] = Field(default_factory=list)
    event_type: str | None = None
    expected_participant_count: int | None = None
    content_language: str | None = None


class ExternalParticipantRead(BaseModel):
    id: int
    name: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    company: str | None = None
    membership_tier: str
    enrichment_status: str
    participant_status: str


class ExternalParticipantDetailRead(BaseModel):
    id: int
    name: str
    tier: str
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None
    company: str | None = None
    website: str | None = None
    industry: str | None = None
    looking_for: str | None = Field(default=None, description="Mapped from the QBCals company needs field")
    offering: str | None = Field(default=None, description="Mapped from the QBCals company offerings field")
    summary: str | None = None
    products: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


def _split_name(name: str) -> tuple[str | None, str | None]:
    parts = name.strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _get_event_participants(db: Session, event_id: int) -> list[Participant]:
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    return db.query(Participant).filter(Participant.event_id == event_id).all()


@router.get("/events", response_model=list[ExternalEventRead])
def external_events(db: Session = Depends(get_db)) -> list[ExternalEventRead]:
    """Return every event known to QBCals."""
    events = db.query(Event).order_by(Event.created_at.desc()).all()
    return [
        ExternalEventRead(
            id=event.id,
            name=event.name,
            date=event.date,
            description=event.description,
            status=event.status,
            agenda=event.agenda,
            matching_goals=event.matching_goals,
            target_sectors=event.target_sectors or [],
            event_type=event.event_type,
            expected_participant_count=event.expected_participant_count,
            content_language=event.content_language,
        )
        for event in events
    ]


@router.get("/events/{event_id}/participants", response_model=list[ExternalParticipantRead])
def external_event_participants(event_id: int, db: Session = Depends(get_db)) -> list[ExternalParticipantRead]:
    """Return the participants QBCals holds for one event."""
    participants = _get_event_participants(db, event_id)
    rows: list[ExternalParticipantRead] = []
    for participant in participants:
        first_name, last_name = _split_name(participant.name)
        rows.append(
            ExternalParticipantRead(
                id=participant.id,
                name=participant.name,
                first_name=first_name,
                last_name=last_name,
                email=participant.email,
                company=participant.company,
                membership_tier=participant.membership_tier,
                enrichment_status=participant.enrichment_status,
                participant_status=participant.participant_status,
            )
        )
    return rows


@router.get(
    "/events/{event_id}/participants/csv",
    response_class=Response,
    responses={200: {"description": "Participants data in CSV format", "content": {"text/csv": {}}}},
)
def external_event_participants_csv(event_id: int, db: Session = Depends(get_db)) -> Response:
    """Download the QBCals participants for one event as CSV."""
    participants = external_event_participants(event_id, db)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDNAMES)
    writer.writeheader()
    for participant in participants:
        writer.writerow(participant.model_dump(include=set(CSV_FIELDNAMES)))

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=participants_{event_id}.csv"},
    )


@router.get("/events/{event_id}/participants/{participant_id}", response_model=ExternalParticipantDetailRead)
def external_participant_detail(event_id: int, participant_id: int, db: Session = Depends(get_db)) -> ExternalParticipantDetailRead:
    """Return the enriched QBCals profile for one participant."""
    participant = (
        db.query(Participant).filter(Participant.id == participant_id, Participant.event_id == event_id).first()
    )
    if participant is None:
        raise HTTPException(status_code=404, detail=f"Participant {participant_id} not found in event {event_id}")

    profile = participant.structured_profile or {}
    company_profile = profile.get("company") or {}

    flags = []
    if participant.participant_status == "review":
        flags.append("review")
    if participant.enrichment_status == "failed":
        flags.append("enrichment_failed")
    if participant.matching_status == "failed":
        flags.append("matching_failed")

    return ExternalParticipantDetailRead(
        id=participant.id,
        name=participant.name,
        tier=participant.membership_tier,
        email=participant.email,
        phone=participant.phone,
        job_title=participant.designation,
        linkedin_url=participant.linkedin_url,
        company=participant.company or company_profile.get("name"),
        website=participant.website or company_profile.get("website"),
        industry=company_profile.get("industry"),
        looking_for=participant.looking_for,
        offering=participant.offerings,
        summary=company_profile.get("summary"),
        products=company_profile.get("products") or [],
        services=company_profile.get("services") or [],
        markets=company_profile.get("markets") or [],
        flags=flags,
    )
