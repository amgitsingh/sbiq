from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.event import Event
from app.models.participant import EnrichmentStatus, Participant
from app.services.ingestion import run_ingestion_pipeline
from app.workers.enrichment_tasks import batch_enrich_event

router = APIRouter(prefix="/events", tags=["events"])


class EventCreate(BaseModel):
    name: str
    date: str | None = None
    description: str | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    date: str | None = None
    description: str | None = None
    status: str


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None = None
    company: str | None = None
    membership_tier: str
    enrichment_status: str
    participant_status: str


class UploadSummary(BaseModel):
    total_rows: int
    parse_skipped: int
    valid: int
    flagged: int
    rejected: int
    unmapped_headers: list[str]
    rejected_details: list[dict]


class EnrichmentTriggerResult(BaseModel):
    event_id: int
    dispatched: int


def _get_event_or_404(event_id: int, db: Session) -> Event:
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    return event


@router.post("", response_model=EventOut, status_code=201)
def create_event(payload: EventCreate, db: Session = Depends(get_db)) -> Event:
    event = Event(name=payload.name, date=payload.date, description=payload.description)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db)) -> list[Event]:
    return db.query(Event).order_by(Event.created_at.desc()).all()


@router.get("/{event_id}/participants", response_model=list[ParticipantOut])
def list_participants(event_id: int, db: Session = Depends(get_db)) -> list[Participant]:
    _get_event_or_404(event_id, db)
    return db.query(Participant).filter(Participant.event_id == event_id).all()


@router.post("/{event_id}/upload", response_model=UploadSummary)
def upload_participants(
    event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> UploadSummary:
    _get_event_or_404(event_id, db)

    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="Uploaded file is missing a filename")

    file_bytes = file.file.read()

    try:
        result = run_ingestion_pipeline(file_bytes, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if result.total_rows == 0:
        raise HTTPException(status_code=400, detail="No valid rows found in uploaded file")

    participants = [
        Participant(
            event_id=event_id,
            participant_status=record.participant_status,
            enrichment_status=EnrichmentStatus.pending,
            raw_source_data=record.raw_source_data,
            **record.fields,
        )
        for record in result.participants
    ]
    db.add_all(participants)
    db.commit()

    return UploadSummary(
        total_rows=result.total_rows,
        parse_skipped=result.parse_skipped,
        valid=result.valid_count,
        flagged=result.flagged_count,
        rejected=result.rejected_count,
        unmapped_headers=result.unmapped_headers,
        rejected_details=result.rejected_details,
    )


@router.post("/{event_id}/enrich", response_model=EnrichmentTriggerResult, status_code=202)
def trigger_enrichment(event_id: int, db: Session = Depends(get_db)) -> EnrichmentTriggerResult:
    """Dispatch enrichment for every participant in the event. A separate,
    deliberate action rather than automatic on upload - enrichment spends real
    Tavily/OpenAI credits, and an organizer may want to fix flagged rows first.
    Requires a Celery worker consuming the 'enrichment' queue to actually
    process the dispatched jobs.
    """
    _get_event_or_404(event_id, db)
    result = batch_enrich_event(event_id)
    return EnrichmentTriggerResult(**result)
