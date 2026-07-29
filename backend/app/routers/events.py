from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models.enrichment_job import EnrichmentJob
from app.models.event import Event
from app.models.match import Match
from app.models.participant import EnrichmentStatus, Participant
from app.models.participant_embedding import ParticipantEmbedding
from app.services.ingestion import run_ingestion_pipeline
from app.services.matching.cost_estimator import estimate_matching_run_cost
from app.services.matching.decision_authority import classify_seniority
from app.workers.embedding_tasks import batch_embed_event
from app.workers.enrichment_tasks import batch_enrich_event
from app.workers.matching_tasks import batch_match_event

# Rough per-job wall-clock estimate for a single embedding API call
# (OpenAI text-embedding-3-small round-trip) - used only to give the caller a
# ballpark, not a scheduling guarantee. Actual throughput depends on Celery
# worker concurrency, which this endpoint has no visibility into.
ESTIMATED_SECONDS_PER_EMBEDDING_JOB = 3

# Rough per-job wall-clock estimate for one match_participant run (a free/local
# rule-engine pass plus one real LLM reasoning call) - based on real observed
# timings during Task 32's live verification (~1-7s depending on match count).
ESTIMATED_SECONDS_PER_MATCH_JOB = 8

DEFAULT_MATCHES_LIMIT = 50
MAX_MATCHES_LIMIT = 200

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


class SourceStatusOut(BaseModel):
    source: str
    status: str
    error_message: str | None = None


class ParticipantEnrichmentStatusOut(BaseModel):
    participant_id: int
    name: str
    enrichment_status: str
    sources: list[SourceStatusOut]


class EnrichmentStatusSummary(BaseModel):
    total: int
    pending: int
    enriching: int
    done: int
    failed: int
    participants: list[ParticipantEnrichmentStatusOut]


class EmbedTriggerResult(BaseModel):
    event_id: int
    dispatched: int
    estimated_completion_seconds: int


class MatchCostBreakdown(BaseModel):
    participant_count: int
    matching_eligible_count: int
    embedding_cost_usd: float
    llm_cost_usd: float
    total_cost_usd: float


class MatchTriggerResult(BaseModel):
    event_id: int
    confirmed: bool
    cost: MatchCostBreakdown
    job_id: str | None = None
    estimated_duration_seconds: int | None = None


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


class ParticipantPersonDetailOut(BaseModel):
    name: str
    title: str | None = None
    # "senior" / "mid_level" / null - derived on the fly from `designation` via
    # the same classifier the rule engine's decision_authority_score uses
    # (app.services.matching.decision_authority.classify_seniority), not a
    # stored field. Nabarun's sample used a richer label ("owner") than our
    # classifier distinguishes - ours is a 3-bucket classifier, not a titled
    # role lookup.
    decision_authority: str | None = None
    linkedin_url: str | None = None
    # Not in Nabarun's shape - ours, kept because it's real and valuable.
    ecosystem_role: str | None = None


class ParticipantCompanyDetailOut(BaseModel):
    name: str | None = None
    website: str | None = None
    employees: str | None = None
    # Nabarun's shape nests "needs" under company - here it's participant.
    # looking_for verbatim (CLAUDE.md's verbatim-from-Excel guarantee), not an
    # LLM-synthesized field.
    needs: str | None = None
    # Not in Nabarun's shape - the natural counterpart to `needs`, real data
    # we have (participant.offerings, also verbatim).
    offerings: str | None = None
    industry: str | None = None
    products: list[str] = []
    services: list[str] = []
    markets: list[str] = []
    customers: list[str] = []
    technologies: list[str] = []
    headquarters: str | None = None
    funding_stage: str | None = None
    investors: list[str] = []
    recent_news: list[str] = []
    summary: str | None = None
    # The following Nabarun-shape fields are deliberately always null - this
    # app's enrichment schema is fact-only by design (no inferential/
    # LLM-guessed business judgments like a budget-band or market-position
    # estimate). Kept here only for shape parity with
    # docs/nabaruns-enrichment-example.json.
    classification: str | None = None
    market_position: str | None = None
    commercial_proposition: str | None = None
    ideal_counterpart: str | None = None
    amsterdam_visibility: str | None = None
    estimated_budget_band: str | None = None
    existing_partnerships: list[str] = []


class ParticipantEnrichmentDetailOut(BaseModel):
    # research_sources: real, deterministically-collected URLs (never
    # LLM-produced - see llm_normalizer.normalize_participant_profile).
    sources: list[str] = []
    # Closest real analog to Nabarun's "notes" - the LLM's own synthesized
    # company.summary.
    notes: str | None = None
    # Always null - this app doesn't compute a confidence score (part of the
    # same "fact-only, no inferential fields" decision as company.
    # market_position etc. above).
    confidence: float | None = None
    research_confidence: float | None = None


class ParticipantDetailOut(BaseModel):
    id: int
    tier: str
    flags: list[str] = []
    person: ParticipantPersonDetailOut
    email: str | None = None
    phone: str | None = None
    company: ParticipantCompanyDetailOut
    enrichment: ParticipantEnrichmentDetailOut


_SENIORITY_LABELS = {1.0: "senior", 0.5: "mid_level"}


@router.get("/{event_id}/participants/{participant_id}", response_model=ParticipantDetailOut)
def get_participant_detail(event_id: int, participant_id: int, db: Session = Depends(get_db)) -> ParticipantDetailOut:
    """Full participant detail, shaped to mirror
    docs/nabaruns-enrichment-example.json's schema as closely as this app's
    actual data supports.

    Every field either maps 1:1 to a real column/structured_profile value, or
    is explicitly always-null with a comment explaining why (this app's
    enrichment is deliberately fact-only - no invented business judgments) -
    never a fabricated guess dressed up to fit Nabarun's shape.
    """
    _get_event_or_404(event_id, db)

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

    return ParticipantDetailOut(
        id=participant.id,
        tier=participant.membership_tier,
        flags=flags,
        person=ParticipantPersonDetailOut(
            name=participant.name,
            title=participant.designation,
            decision_authority=_SENIORITY_LABELS.get(classify_seniority(participant.designation)),
            linkedin_url=participant.linkedin_url,
            ecosystem_role=profile.get("ecosystem_role"),
        ),
        email=participant.email,
        phone=participant.phone,
        company=ParticipantCompanyDetailOut(
            name=participant.company or company_profile.get("name"),
            website=participant.website or company_profile.get("website"),
            employees=company_profile.get("employee_count"),
            needs=participant.looking_for,
            offerings=participant.offerings,
            industry=company_profile.get("industry"),
            products=company_profile.get("products") or [],
            services=company_profile.get("services") or [],
            markets=company_profile.get("markets") or [],
            customers=company_profile.get("customers") or [],
            technologies=company_profile.get("technologies") or [],
            headquarters=company_profile.get("headquarters"),
            funding_stage=company_profile.get("funding_stage"),
            investors=company_profile.get("investors") or [],
            recent_news=company_profile.get("recent_news") or [],
            summary=company_profile.get("summary"),
        ),
        enrichment=ParticipantEnrichmentDetailOut(
            sources=profile.get("research_sources") or [],
            notes=company_profile.get("summary"),
        ),
    )


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
    # Celery's @task(bind=True) auto-supplies `self` at runtime (Task.__call__
    # binds the task instance), but its type stubs treat the decorator as
    # identity-preserving, so Pylance still sees the original (self, event_id)
    # signature and misreads this single-argument call as missing event_id.
    result = batch_enrich_event(event_id)  # type: ignore[call-arg]
    return EnrichmentTriggerResult(**result)


@router.get("/{event_id}/enrichment-status", response_model=EnrichmentStatusSummary)
def get_enrichment_status(event_id: int, db: Session = Depends(get_db)) -> EnrichmentStatusSummary:
    """Per-participant enrichment status with a per-source breakdown, plus
    aggregate counts. If a participant's enrichment ran more than once
    (e.g. a Celery retry after a failed LLM normalization), only the most
    recent EnrichmentJob row per source is shown - earlier rows from prior
    attempts stay in the DB but aren't surfaced here.
    """
    _get_event_or_404(event_id, db)

    participants = db.query(Participant).filter(Participant.event_id == event_id).all()
    participant_ids = [p.id for p in participants]

    jobs = (
        db.query(EnrichmentJob)
        .filter(EnrichmentJob.participant_id.in_(participant_ids))
        .order_by(EnrichmentJob.created_at)
        .all()
    )

    latest_job: dict[tuple[int, str], EnrichmentJob] = {}
    for job in jobs:
        latest_job[(job.participant_id, job.source)] = job

    counts = {"pending": 0, "enriching": 0, "done": 0, "failed": 0}
    participants_out = []
    for p in participants:
        counts[p.enrichment_status] += 1
        sources = [
            SourceStatusOut(source=source, status=job.status, error_message=job.error_message)
            for (participant_id, source), job in latest_job.items()
            if participant_id == p.id
        ]
        participants_out.append(
            ParticipantEnrichmentStatusOut(
                participant_id=p.id,
                name=p.name,
                enrichment_status=p.enrichment_status,
                sources=sources,
            )
        )

    return EnrichmentStatusSummary(
        total=len(participants),
        pending=counts["pending"],
        enriching=counts["enriching"],
        done=counts["done"],
        failed=counts["failed"],
        participants=participants_out,
    )


@router.post("/{event_id}/embed", response_model=EmbedTriggerResult, status_code=202)
def trigger_embedding(event_id: int, db: Session = Depends(get_db)) -> EmbedTriggerResult:
    """Dispatch embedding generation for every enriched participant in the
    event. Callable only after enrichment has finished - rejects while any
    participant is still 'pending' or 'enriching', since running this early
    would just embed a partial set and silently miss the rest (there's no
    automatic re-trigger once the remaining participants finish enriching).

    In the normal flow this is redundant - enrich_participant already embeds
    automatically (Task 23). This is the manual path: backfilling
    participants enriched before that existed, or retrying ones whose
    automatic embedding attempt failed and was swallowed.
    """
    _get_event_or_404(event_id, db)

    statuses = [
        s for (s,) in db.query(Participant.enrichment_status).filter(Participant.event_id == event_id).all()
    ]
    if not statuses:
        raise HTTPException(status_code=400, detail="This event has no participants yet")
    if any(s in (EnrichmentStatus.pending, EnrichmentStatus.enriching) for s in statuses):
        raise HTTPException(status_code=400, detail="Enrichment is still in progress for this event")

    # Same Pylance/Celery bind=True false positive as trigger_enrichment above.
    result = batch_embed_event(event_id)  # type: ignore[call-arg]
    dispatched = result["dispatched"]
    return EmbedTriggerResult(
        event_id=event_id,
        dispatched=dispatched,
        estimated_completion_seconds=dispatched * ESTIMATED_SECONDS_PER_EMBEDDING_JOB,
    )


@router.post("/{event_id}/match", response_model=MatchTriggerResult)
def trigger_matching(
    event_id: int, response: Response, confirm: bool = False, db: Session = Depends(get_db)
) -> MatchTriggerResult:
    """Cost-gated trigger for a matching run, per CLAUDE.md's "estimated cost
    shown before triggering matching run": called without `?confirm=true`,
    this only returns the cost breakdown (HTTP 200, nothing dispatched) -
    call it again with `?confirm=true` once you've reviewed the number to
    actually enqueue the run (HTTP 202).

    Requires every enriched participant to already be embedded (rejects
    otherwise, naming the shortfall so the caller knows to run
    POST /events/{id}/embed first) - matching without embeddings would just
    silently produce empty candidate pools for everyone.

    Dispatches batch_match_event asynchronously (unlike /enrich and /embed,
    which call their batch task directly and return an immediate dispatched
    count) - this task explicitly asks for a job ID back, so the caller can
    look the run up later via Celery's result backend.
    """
    _get_event_or_404(event_id, db)

    enriched = (
        db.query(Participant)
        .filter(Participant.event_id == event_id, Participant.enrichment_status == EnrichmentStatus.done)
        .all()
    )
    if not enriched:
        raise HTTPException(status_code=400, detail="No enriched participants in this event yet")

    embedded_ids = {
        pid
        for (pid,) in db.query(ParticipantEmbedding.participant_id)
        .filter(ParticipantEmbedding.event_id == event_id)
        .all()
    }
    missing = [p.id for p in enriched if p.id not in embedded_ids]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(missing)} enriched participant(s) are not embedded yet - "
                f"run POST /events/{event_id}/embed first"
            ),
        )

    cost = MatchCostBreakdown(**estimate_matching_run_cost(db, event_id=event_id))

    if not confirm:
        response.status_code = status.HTTP_200_OK
        return MatchTriggerResult(event_id=event_id, confirmed=False, cost=cost)

    response.status_code = status.HTTP_202_ACCEPTED
    # Celery's @task(bind=True) auto-supplies `self` at runtime - same Pylance
    # false positive noted on the other trigger endpoints above, but .delay()
    # is a real Task method the stubs do see correctly, so no ignore needed here.
    async_result = batch_match_event.delay(event_id)
    return MatchTriggerResult(
        event_id=event_id,
        confirmed=True,
        cost=cost,
        job_id=async_result.id,
        estimated_duration_seconds=cost.matching_eligible_count * ESTIMATED_SECONDS_PER_MATCH_JOB,
    )


class MatchParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None = None
    company: str | None = None


class MatchOut(BaseModel):
    id: int
    participant_a: MatchParticipantOut
    participant_b: MatchParticipantOut
    rank: int | None = None
    score: float | None = None
    reasoning: list[str] | None = None
    email_draft: str | None = None
    linkedin_draft: str | None = None
    status: str
    mutual: bool


class PaginatedMatchesOut(BaseModel):
    total: int
    limit: int
    offset: int
    matches: list[MatchOut]


def _dedupe_pair_rows(matches: list[Match]) -> list[tuple[Match, bool]]:
    """Collapse A->B / B->A row pairs down to one row per unordered pair.

    Every stored pair has at least one genuine (is_bidirectional=False) row -
    store_match always writes the genuine side itself, only auto-creating the
    reverse as a placeholder if it didn't already exist (Task 30). So a
    genuine row always wins over a placeholder; where both directions are
    genuine (each side independently selected the other), that pair is
    "mutual" and the lower id wins, purely for deterministic output.

    Returns (representative_row, mutual) pairs, mutual meaning both sides
    independently selected each other - the placeholder case is never mutual,
    since a placeholder was never anyone's own real selection.
    """
    best: dict[frozenset[int], Match] = {}
    mutual: dict[frozenset[int], bool] = {}

    for m in matches:
        pair_key = frozenset((m.participant_a_id, m.participant_b_id))
        current = best.get(pair_key)
        if current is None:
            best[pair_key] = m
            mutual[pair_key] = False
            continue

        if not current.is_bidirectional and not m.is_bidirectional:
            mutual[pair_key] = True
            if m.id < current.id:
                best[pair_key] = m
        elif current.is_bidirectional and not m.is_bidirectional:
            best[pair_key] = m

    return sorted(((best[k], mutual[k]) for k in best), key=lambda pair: pair[0].id)


@router.get("/{event_id}/matches", response_model=PaginatedMatchesOut)
def list_matches(
    event_id: int,
    limit: int = DEFAULT_MATCHES_LIMIT,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> PaginatedMatchesOut:
    """One row per match pair (deduplicated - A->B and B->A are the same
    relationship, not two matches), paginated.

    No status filter - returns every pair regardless of MatchStatus
    (pending/approved/rejected). Ordered by id, so pagination is stable
    across calls even as new matches are added between pages.
    """
    _get_event_or_404(event_id, db)

    if limit < 1 or limit > MAX_MATCHES_LIMIT:
        raise HTTPException(status_code=400, detail=f"limit must be between 1 and {MAX_MATCHES_LIMIT}")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    all_matches = (
        db.query(Match)
        .filter(Match.event_id == event_id)
        .options(joinedload(Match.participant_a), joinedload(Match.participant_b))
        .order_by(Match.id)
        .all()
    )
    deduped = _dedupe_pair_rows(all_matches)
    total = len(deduped)
    page = deduped[offset : offset + limit]

    return PaginatedMatchesOut(
        total=total,
        limit=limit,
        offset=offset,
        matches=[
            MatchOut(
                id=m.id,
                participant_a=MatchParticipantOut.model_validate(m.participant_a),
                participant_b=MatchParticipantOut.model_validate(m.participant_b),
                rank=m.rank,
                score=m.score,
                reasoning=m.reasoning,
                email_draft=m.email_draft,
                linkedin_draft=m.linkedin_draft,
                status=m.status,
                mutual=is_mutual,
            )
            for m, is_mutual in page
        ],
    )


class ParticipantMatchOut(BaseModel):
    participant: MatchParticipantOut
    rank: int | None = None
    score: float | None = None
    reasoning: list[str] | None = None
    email_draft: str | None = None
    linkedin_draft: str | None = None
    status: str
    # True if this recipient's own matching run independently selected this
    # counterpart (a genuine match_writer.store_match row - has real
    # personalized drafts). False means this match was only auto-received via
    # CLAUDE.md's bidirectional-matching rule (the counterpart selected this
    # recipient, not the other way around) - email_draft/linkedin_draft are
    # null in that case, since they were never generated from this
    # recipient's perspective. See match_writer.store_match's docstring.
    self_selected: bool


class ParticipantMatchesOut(BaseModel):
    recipient: MatchParticipantOut
    matches: list[ParticipantMatchOut]


@router.get("/{event_id}/participants/{participant_id}/matches", response_model=ParticipantMatchesOut)
def get_participant_matches(event_id: int, participant_id: int, db: Session = Depends(get_db)) -> ParticipantMatchesOut:
    """One participant's own match list - the "recipient -> matches" shape,
    mirroring docs/nabaruns-enrichment-example.json's response format.

    Rows are looked up by participant_a_id == participant_id: per
    match_writer.store_match, participant_a is always "self" on a row -
    genuine self-selected matches (is_bidirectional=False) and matches
    auto-received via the bidirectional rule (is_bidirectional=True) both
    land here already correctly signed for this participant's perspective,
    with no dedup needed (unlike list_matches, this is a directional view by
    design, not a pair-level one).

    Ordered by rank ascending (nulls last) - the LLM's own best-to-worst
    ranking of this participant's final 3-5 matches.
    """
    _get_event_or_404(event_id, db)

    participant = (
        db.query(Participant).filter(Participant.id == participant_id, Participant.event_id == event_id).first()
    )
    if participant is None:
        raise HTTPException(status_code=404, detail=f"Participant {participant_id} not found in event {event_id}")

    rows = (
        db.query(Match)
        .filter(Match.event_id == event_id, Match.participant_a_id == participant_id)
        .options(joinedload(Match.participant_b))
        .order_by(Match.rank.asc().nulls_last())
        .all()
    )

    return ParticipantMatchesOut(
        recipient=MatchParticipantOut.model_validate(participant),
        matches=[
            ParticipantMatchOut(
                participant=MatchParticipantOut.model_validate(m.participant_b),
                rank=m.rank,
                score=m.score,
                reasoning=m.reasoning,
                email_draft=m.email_draft,
                linkedin_draft=m.linkedin_draft,
                status=m.status,
                self_selected=not m.is_bidirectional,
            )
            for m in rows
        ],
    )
