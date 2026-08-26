"""Studio events routes — in-process replacement for the old IndMatchmaking
HTTP proxy to QBCals (docs/PLAN.md Phase 8, Task 62).

Ported from IndMatchmaking (D:\\Python\\IndMatchmaking\\src\\app\\domain\\studio\\
controller.py + service.py + schemas.py). The original proxied every call
over HTTP via app/lib/qbcals.py to this very app's own /events endpoints
(QBCALS_API_BASE_URL). Now that both live in one process, these handlers
call QBCals' own create_event/list_events/_get_event_or_404
(app/routers/events.py) as plain Python function calls - Task 59's
owner-scoped access control applies automatically, since these handlers
resolve and pass through the exact same current_user/role_name dependencies
the native routes use. Only the response/request shape is adapted to the
StudioEvent*/StudioEventCreate contract the Studio frontend already expects
at /studio/events (this repo drops the /api prefix IndMatchmaking used,
same convention as every other ported router in this phase - see auth.py).

Only the three events routes are in scope for Task 62. Upload/enrich/embed/
match/matches/review/send follow in Tasks 63-65, appended to this same
router as they're ported.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import UserMaster
from app.routers import events as events_router
from app.services.auth.deps import current_admin

router = APIRouter(prefix="/studio", tags=["studio"], dependencies=[Depends(current_admin)])


class StudioTargetSector(StrEnum):
    """Mirrors events.py's SUGGESTED_TARGET_SECTORS, enforced here (unlike
    the native EventCreate, which leaves this unenforced by design - see
    that model's own docstring) so the Studio API renders real dropdowns.
    """

    FINANCE_BANKING = "finance_banking"
    REAL_ESTATE = "real_estate"
    HEALTH_WELLNESS = "health_wellness"
    HOSPITALITY_TOURISM = "hospitality_tourism"
    CULTURE_ENTERTAINMENT = "culture_entertainment"
    MEDIA_PHOTOGRAPHY = "media_photography"
    EDUCATION_TRAINING = "education_training"
    ADMINISTRATIVE_HR = "administrative_hr"
    TECHNOLOGY = "technology"
    RETAIL_ECOMMERCE = "retail_ecommerce"
    MANUFACTURING = "manufacturing"
    CONSULTING = "consulting"
    LEGAL = "legal"
    LOGISTICS = "logistics"
    CONSTRUCTION = "construction"
    AGRICULTURE_FOOD = "agriculture_food"
    ENERGY = "energy"
    NONPROFIT_GOVERNMENT = "nonprofit_government"
    TELECOMMUNICATIONS = "telecommunications"


class StudioEventType(StrEnum):
    NETWORKING = "networking"
    PITCH_DAY = "pitch_day"
    CONFERENCE = "conference"
    TRADE_SHOW = "trade_show"
    WORKSHOP = "workshop"
    MIXER = "mixer"
    PANEL = "panel"


class StudioContentLanguage(StrEnum):
    EN = "en"
    NL = "nl"


class StudioEvent(BaseModel):
    """Mirrors events.py's EventOut. Plain strings (not enums) on read, same
    reasoning as the original: an event created through another client could
    hold anything, and a strict read model shouldn't fail the whole listing
    over one unrecognized value.
    """

    model_config = ConfigDict(from_attributes=True)

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

    @field_validator("target_sectors", mode="before")
    @classmethod
    def _null_to_empty(cls, value: object) -> object:
        """QBCals' Event.target_sectors is nullable; the Studio contract
        always returns a list."""
        return [] if value is None else value


class StudioEventList(BaseModel):
    events: list[StudioEvent] = Field(default_factory=list)


class StudioEventCreate(BaseModel):
    """Mirrors events.py's EventCreate, but enforces the suggested
    sector/type values as real enums (unlike the native model) so a typo
    fails locally instead of reaching the matching pipeline unusable.
    """

    name: str = Field(min_length=1, max_length=200)
    date: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    agenda: str | None = Field(default=None, max_length=5000)
    matching_goals: str | None = Field(default=None, max_length=2000)
    target_sectors: list[StudioTargetSector] | None = Field(
        default=None,
        description="Sectors this event targets. Select any number of the suggested values.",
    )
    event_type: StudioEventType | None = Field(
        default=None,
        description="Type of event. Select one of the suggested values.",
    )
    expected_participant_count: int | None = Field(default=None, ge=0)
    content_language: StudioContentLanguage | None = Field(
        default=None,
        description="Language for LLM-generated content. Omitted is treated as 'en' by QBCals.",
    )


@router.get("/events", response_model=StudioEventList)
def studio_events(
    db: Session = Depends(get_db),
    current_user: UserMaster = Depends(current_admin),
    role_name: str | None = Depends(events_router.current_user_role_name),
) -> StudioEventList:
    """Return every event the current user can see, calling QBCals' own
    list_events directly - Task 59's owner-scoping applies exactly as it
    does on GET /events."""
    events = events_router.list_events(db=db, current_user=current_user, role_name=role_name)
    return StudioEventList(events=[StudioEvent.model_validate(event) for event in events])


@router.post("/events", response_model=StudioEvent, status_code=status.HTTP_201_CREATED)
def studio_create_event(
    payload: StudioEventCreate,
    db: Session = Depends(get_db),
    current_user: UserMaster = Depends(current_admin),
) -> StudioEvent:
    """Create one event, calling QBCals' own create_event directly - the
    created event is stamped with owner_user_id=current_user.id exactly as
    POST /events does."""
    native_payload = events_router.EventCreate(
        name=payload.name,
        date=payload.date,
        description=payload.description,
        agenda=payload.agenda,
        matching_goals=payload.matching_goals,
        target_sectors=[sector.value for sector in payload.target_sectors] if payload.target_sectors else None,
        event_type=payload.event_type.value if payload.event_type else None,
        expected_participant_count=payload.expected_participant_count,
        content_language=payload.content_language.value if payload.content_language else None,
    )
    event = events_router.create_event(native_payload, db=db, current_user=current_user)
    return StudioEvent.model_validate(event)


@router.get("/events/{event_id}", response_model=StudioEvent)
def studio_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: UserMaster = Depends(current_admin),
    role_name: str | None = Depends(events_router.current_user_role_name),
) -> StudioEvent:
    """Return one event, calling QBCals' own _get_event_or_404 directly -
    QBCals exposes no native GET /events/{id}, so this is the first caller
    of that helper outside events.py itself. 403s exactly as the native
    routes do when the event exists but isn't owned by the current user."""
    event = events_router._get_event_or_404(event_id, db, current_user, role_name)
    return StudioEvent.model_validate(event)
