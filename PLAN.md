# QBCals — Implementation Plan

AI-powered business event matchmaking platform. Replaces manual matching with a 6-step automated pipeline:
**Excel → Enrich (5 sources) → Merge → LLM normalize → Embed → pgvector → Similarity search → Rule engine → LLM reasoning → Matches**

Frontend and admin panel are handled separately. This plan covers backend only.

---

## Phase 1 — Foundation
> Project scaffold, database schema, async infrastructure. Everything else builds on this.

| # | Task | Description | Status |
|---|---|---|---|
| 1 | **FastAPI project structure** | Scaffold the full folder layout: `app/models`, `app/routers`, `app/services`, `app/workers`, `app/core`. Create `main.py` entry point and `requirements.txt` with all dependencies (fastapi, uvicorn, sqlalchemy, alembic, celery, redis, openai, playwright, beautifulsoup4, openpyxl, tavily-python, pgvector, supabase, python-dotenv). | `done` |
| 2 | **Environment config (.env.example)** | Document every required environment variable with descriptions: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL`, `TAVILY_API_KEY`, `CRUNCHBASE_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`. | `done` |
| 3 | **SQLAlchemy models** | Define four core models. `Event`: id, name, date, description, status. `Participant`: id, event_id, name, email, company, designation, sector, company_size, membership_tier, looking_for, offerings, linkedin_url, website, enrichment_status, structured_profile (JSON). `Match`: id, event_id, participant_a_id, participant_b_id, rank, reasoning (JSON array), email_draft, linkedin_draft, status (pending/approved/rejected), is_bidirectional. `EnrichmentJob`: id, participant_id, source, status, raw_data (JSON), error_message, created_at. | `done` |
| 4 | **Alembic migrations + local SQLite** | Initialize Alembic, generate the initial migration from models, configure dual-database support: SQLite for local dev and PostgreSQL (Supabase) in production via `DATABASE_URL`. Include pgvector extension enablement (`CREATE EXTENSION IF NOT EXISTS vector`) in the migration. | `done` |
| 5 | **Celery + Redis worker** | Set up Celery app in `app/workers/celery_app.py` with Redis as broker and result backend. Create two separate queues: `enrichment` and `matching` so they can be scaled independently. Create worker entrypoint script. | `done` |
| 6 | **pgvector schema** | Create `participant_embeddings` table: id, participant_id, event_id, embedding (vector 1536 dimensions for text-embedding-3-small), structured_profile_snapshot (JSON), created_at. Add HNSW index on the embedding column for fast ANN search. Add a separate index on event_id for filtered queries. | `done` |

> **Schema refinement (2026-07-15):** reviewing a real sample export (`data/data.xlsx`)
> surfaced fields the original `Participant` model didn't cover. Migration `0003` added
> `phone`, `ideal_connection`, `biggest_opportunity`, and a catch-all `raw_source_data`
> JSON column (full original row, for any future organizer-specific question). No task
> numbers changed — this refines Task 3's schema ahead of Tasks 8–11.

---

## Phase 2 — Data Ingestion
> Parse the uploaded Excel/CSV, normalize it, validate it, and store clean participant records.

| # | Task | Description | Status |
|---|---|---|---|
| 7 | **Excel/CSV parser** | Parse `.xlsx` and `.csv` uploads using openpyxl. Extract rows into raw dicts. Handle merged cells, empty rows, and encoding issues. Return two lists: valid raw rows and skipped rows with skip reasons. Never raise on malformed rows — log and skip. | `done` |
| 8 | **Dutch/English header auto-mapper** | Maintain a canonical mapping of Dutch and English column header synonyms to internal field names (e.g., `"Bedrijfsnaam"`, `"Company Name"`, `"company"` → `"company"`). Apply fuzzy string matching as a fallback for near-matches. Return unmapped columns as warnings (not errors) so the upload still proceeds. | `done` |
| 9 | **Data validation + sparse row flagging** | Validate each participant row after mapping. Required fields (reject if missing): name, email, company. Warn-level fields: looking_for, offerings — if both are missing, flag the participant for admin review but do not drop them. Validate email format. Normalize whitespace. Return three buckets: valid, flagged (needs review), rejected. | `done` |
| 10 | **Membership tier normalizer** | Map free-text tier values from the Excel to a canonical enum: `sponsor`, `premium_member`, `business_member`, `normal_member`, `non_member`. Handle common Dutch and English variants (e.g., `"Premium Lid"`, `"SPONSOR"`, `"Business Partner"`, `"Gewoon Lid"`). Default unrecognized values to `normal_member` and log them. Match quota is flat 3 for all tiers currently — normalizer stores tier for future use only. | `done` |

> **Refinement per confirmed decision:** blank/missing values default to `normal_member`
> (no flag — simply unanswered). Values that indicate *some* confirmed membership but
> not which tier (`"Yes"`) or unparseable garbage (e.g. a phone number typo'd into the
> field) default to `business_member` **and are flagged for admin review**, rather than
> silently downgrading to `normal_member`.

| | | |  |
|---|---|---|---|
| 11 | **Ingestion API endpoints** | `POST /events` — create event with name, date, description. `POST /events/{id}/upload` — accept multipart file upload, run the full ingestion chain (parse → map → validate → normalize tier), bulk insert participants, return a summary JSON (total, valid, flagged, rejected counts). `GET /events/{id}/participants` — list all participants with their enrichment status. `GET /events` — list all events. | `done` |

> **Bug fix while wiring this up:** all `Enum(...)` model columns (`MembershipTier`,
> `EventStatus`, `EnrichmentStatus`, `ParticipantStatus`, `MatchStatus`,
> `EnrichmentSource`, `JobStatus`) defaulted to SQLAlchemy's native-PostgreSQL-enum
> mode, which tried to cast inserts against a DB type (e.g. `::membershiptier`) that
> was never created — the migrations only ever made these columns `VARCHAR`. Fixed by
> adding `native_enum=False` to every `Enum(...)` column across all four model files;
> no migration needed since the DB columns were already `VARCHAR`. Also added an
> explicit `db.rollback()` on exception in `get_db()`.

---

## Phase 3 — Enrichment Pipeline
> For each participant, fetch public data from 5 sources, merge it, and use an LLM to produce a clean structured JSON profile.

| # | Task | Description | Status |
|---|---|---|---|
| 12 | **Company website scraper** | Given a company website URL, launch a headless Playwright browser and fetch the homepage and `/about` page. Parse rendered HTML with BeautifulSoup, stripping nav, footer, and boilerplate. Return clean text capped at 5,000 characters. Handle timeouts (10s limit), 404s, and JS-heavy sites gracefully. Return `None` on any failure — never raise. | `done` |
| 13 | **Tavily web search client** | Given participant name + company name, call the Tavily Search API and return the top 5 result snippets as a combined text block. Query format: `"{person name} {company name} business"`. Cap output at 3,000 characters. Handle API errors and quota exhaustion by returning `None` gracefully. | `pending` |
| 14 | **Tavily news search client** | Given company name, call Tavily in news search mode and return the top 5 recent news snippets. Query format: `"{company name} news funding partnership product launch"`. Cap output at 3,000 characters. Return an empty list on failure — never block the pipeline. | `pending` |
| 15 | **Crunchbase API client** | Given company name, query the Crunchbase API for: employee count, headquarters, funding stage, funding rounds, investor names, founding year, and categories. Map the API response fields to the structured profile schema. Handle 404 (company not found) and rate limits by returning a partial dict with only the fields successfully retrieved. | `pending` |
| 16 | **LinkedIn best-effort scraper** | Given a LinkedIn profile URL from the Excel, attempt a Playwright scrape of the public profile page. Extract: name, current title, company, and about section text. If blocked — login wall, HTTP 999, CAPTCHA, or any exception — catch it, log the reason, and return `None`. Never retry the same participant within one enrichment run. This source is entirely optional; its absence must not block the pipeline. | `pending` |
| 17 | **Company enrichment deduplication cache** | Before running company-level enrichment (website, Tavily, news, Crunchbase), check a Redis cache keyed by `normalized_company_name:event_id`. If a cached result exists, return it immediately without making any external calls. If not cached, run enrichment and store the result with a 24-hour TTL. Person-level fields (designation, looking_for, offerings) are always taken from the participant record directly and are never cached. | `pending` |
| 18 | **Raw enrichment data merger** | Combine outputs from all 5 enrichment sources into a single structured context string. Prefix each section clearly (e.g., `=== WEBSITE ===`, `=== TAVILY ===`, `=== NEWS ===`, `=== CRUNCHBASE ===`, `=== LINKEDIN ===`). Prepend the original Excel fields (name, designation, looking_for, offerings) verbatim at the top. This merged block is the input to the LLM normalization step. | `pending` |
| 19 | **LLM normalization → structured JSON profile** | Send the merged enrichment context to the LLM with JSON mode enforced. The prompt instructs the LLM to: fill all profile schema fields from available context, infer missing fields where reasonable (e.g., funding stage mentioned in a news article), write `company.summary` as a synthesis of all sources, and **never modify `person.looking_for` or `person.offerings`** — copy them verbatim from the Excel section of the context. Validate the LLM response against the profile schema and retry once on validation failure. | `pending` |
| 20 | **Celery enrichment tasks** | `enrich_participant_task(participant_id)`: run all 5 enrichment sources in order → merge → LLM normalize → store the resulting structured JSON on the participant record → update each `EnrichmentJob` row with status and error if any. `batch_enrich_event_task(event_id)`: fan out `enrich_participant_task` for all participants in the event, checking the company deduplication cache before dispatching company-level calls. | `pending` |
| 21 | **Enrichment status API endpoint** | `GET /events/{id}/enrichment-status` — return per-participant enrichment status (pending / enriching / done / failed) with a per-source breakdown for each participant. Include aggregate counts: total participants, enriched, failed, and pending. Used by the frontend to poll enrichment progress in real time. | `pending` |

---

## Phase 4 — Embedding & Vector Storage
> Convert each enriched profile into a vector and store it in pgvector for similarity search.

| # | Task | Description | Status |
|---|---|---|---|
| 22 | **Embedding generation service** | Serialize the structured JSON profile to a flat text string (person fields first, then company fields, in a consistent format). Call the OpenAI `text-embedding-3-small` API to get a 1536-dimension vector. Handle API errors with one retry. Log token count per call to support cost tracking. | `pending` |
| 23 | **pgvector upsert service** | Store or update a participant's embedding in the `participant_embeddings` table. Upsert on `(participant_id, event_id)`. Store the embedding vector alongside a snapshot of the structured profile JSON for debugging. Called automatically after LLM normalization completes for each participant. | `pending` |
| 24 | **Event-scoped cosine similarity search** | Given a `participant_id` and `event_id`: fetch the participant's embedding, run a pgvector cosine similarity query with a hard `WHERE event_id = ?` filter — never search across events. Exclude the participant themselves from results. Return the top N candidates (configurable, default 20) with their similarity scores. Output feeds directly into the rule engine. | `pending` |
| 25 | **POST /events/{id}/embed endpoint** | Trigger embedding generation for all enriched participants in an event. Skip any participant whose `enrichment_status` is not `done`. Enqueue embedding jobs as Celery tasks. Return the number of jobs enqueued and an estimated completion time. Callable only after enrichment is complete. | `pending` |

---

## Phase 5 — Matching Engine
> Filter similarity search results through deterministic scoring, then use the LLM to select and justify the final matches.

| # | Task | Description | Status |
|---|---|---|---|
| 26 | **Token overlap scorer** | Tokenize and normalize (lowercase, remove stopwords) the `looking_for` and `offerings` fields. Score a candidate pair A↔B as: `overlap(A.looking_for, B.offerings) + overlap(B.looking_for, A.offerings)`. Return a float 0–1. This is the primary intent-alignment signal in the rule engine. | `pending` |
| 27 | **Sector alignment + company size scorers** | Sector scorer: exact industry match = 1.0, adjacent sector (predefined adjacency map, e.g., fintech ↔ banking) = 0.5, unrelated = 0.0. Company size scorer: same bucket = 1.0, one bucket apart = 0.5, two or more apart = 0.0. Size buckets: 1–10, 11–50, 51–200, 201–1000, 1000+. Both return float 0–1. | `pending` |
| 28 | **Rule engine** | For each participant, take their similarity search candidates and apply composite scoring: `score = (token_overlap × 0.5) + (sector × 0.3) + (size × 0.2)`. Hard exclusions: same-company pairs (matched by normalized company name). Global deduplication: track all seen pairs in a set so A→B and B→A are not both processed. Return the top 5–10 ranked candidates per participant. Process sponsors first, then premium members, then others — so the best candidates are allocated to higher-priority participants first. | `pending` |
| 29 | **LLM matching reasoning service** | Send a participant's full structured JSON profile along with their 5–10 rule engine candidates to the LLM with JSON mode enforced. The prompt instructs the LLM to select the best 3–5 matches and return a structured response: `matches[].participant_id`, `matches[].rank`, `matches[].reasoning` (array of 3 bullet strings), `matches[].email_draft`, `matches[].linkedin_draft`. Validate the response schema. Retry once on invalid schema. Log input and output token counts per call. | `pending` |
| 30 | **Bidirectional match enforcement** | After the LLM selects A→B: check if a match record from B to A already exists. If not, create the reverse record B→A with `is_bidirectional = True` and the same reasoning mirrored. Prevents duplicate pair creation in the case where both A and B independently selected each other through their own matching runs. | `pending` |
| 31 | **Pre-run cost estimator** | Before any matching run: count enriched participants in the event. Estimate embedding token cost (avg profile character length × participant count, converted to tokens, priced against `text-embedding-3-small` rate). Estimate LLM reasoning token cost (avg prompt size with candidates × participant count, priced against the configured model rate). Return a breakdown: embedding cost, LLM cost, total in USD. | `pending` |
| 32 | **Celery matching tasks** | `match_participant_task(participant_id, event_id)`: run similarity search → rule engine → LLM reasoning → store match records → enforce bidirectional. `batch_match_event_task(event_id)`: fan out `match_participant_task` for all embedded participants in the event, respecting tier-based processing order (sponsors dispatched first). Track matching progress per participant. | `pending` |
| 33 | **POST /events/{id}/match endpoint** | Trigger the matching run for an event. Validate that all participants have been embedded. Return the cost estimate and require a `confirm=true` query parameter to actually enqueue the batch job — prevents accidental runs. Enqueue `batch_match_event_task`. Return a job ID and estimated duration. | `pending` |

---

## Phase 6 — Export & Output
> Generate the final deliverable: a downloadable Excel/CSV with all match pairs and reasoning.

| # | Task | Description | Status |
|---|---|---|---|
| 34 | **Excel/CSV export formatter** | Generate an `.xlsx` file with one row per participant: name, email, company, then up to 3 match columns each containing: matched participant name, matched company, 3 reasoning bullets, email draft, LinkedIn draft. Include only approved matches if the organizer has reviewed them, otherwise include all pending matches. Use openpyxl with bold headers and auto-sized columns. | `pending` |
| 35 | **GET /events/{id}/export endpoint** | Stream the generated file as a download response. Accept `?format=csv` for a CSV fallback. Include the event name and date in the filename (e.g., `TechEvent_2026-07-14_matches.xlsx`). Return HTTP 400 with a clear message if matching has not been run yet for the event. | `pending` |

---

## Phase 7 — Testing & Deployment
> Verify correctness at unit, integration, and end-to-end levels. Deploy to production.

| # | Task | Description | Status |
|---|---|---|---|
| 43 | **Unit tests: rule engine scorers** | Test each scorer in isolation using pytest with parametrize. Token overlap: exact match, partial overlap, no overlap, Dutch text. Sector: exact, adjacent, unrelated. Company size: same bucket, one apart, far apart. Composite scoring and final ranking order. Same-company exclusion. Global pair deduplication. | `pending` |
| 44 | **Unit tests: ingestion pipeline** | Test Excel parser with sample `.xlsx` files (valid, sparse rows, missing columns). Test Dutch/English header mapper with a full set of known Dutch variants. Test validator correctly buckets rows as valid, flagged, or rejected. Test tier normalizer handles all known Dutch and English tier string variants. Edge cases: empty file, single-row file, all-Dutch headers. | `pending` |
| 45 | **Integration tests: enrichment pipeline** | Use mocked external sources. Test: all 5 sources succeed → valid structured JSON produced. Test: LinkedIn blocked → pipeline still completes with partial data. Test: Crunchbase down → proceeds without funding data. Test: company deduplication cache is hit for a second participant from the same company. Test: `looking_for` and `offerings` are never modified by LLM normalization step. | `pending` |
| 46 | **Integration tests: matching pipeline** | Use a 10-participant mock dataset with embeddings pre-seeded. Test: similarity search is strictly scoped to event_id. Test: same-company pairs are excluded by the rule engine. Test: LLM output passes schema validation. Test: bidirectional enforcement creates the reverse match record. Test: match quota of 3 is respected per participant. Test: cost estimator returns a non-zero, reasonable estimate. | `pending` |
| 47 | **E2E test + production deployment** | Run the complete pipeline with a real sample Excel (20+ participants) against live APIs. Verify enrichment completes with acceptable partial-failure rate. Verify match quality is meaningful. Fix any integration bugs. Deploy backend to Railway/Render, configure Supabase production instance with pgvector extension enabled. Run smoke tests against the production deployment. | `pending` |

---

## Summary

Task status: `pending` → `done` as each task is completed.

| Phase | Tasks | Scope | Progress |
|---|---|---|---|
| 1 — Foundation | 1–6 | FastAPI scaffold, models, Alembic, Celery + Redis, pgvector schema | 6 / 6 |
| 2 — Data Ingestion | 7–11 | Excel/CSV parse, header mapping, validation, tier normalization, upload API | 5 / 5 |
| 3 — Enrichment Pipeline | 12–21 | 5 enrichment sources, dedup cache, merger, LLM normalization, async Celery jobs | 1 / 10 |
| 4 — Embedding & Vector Storage | 22–25 | Embedding generation, pgvector upsert, event-scoped similarity search | 0 / 4 |
| 5 — Matching Engine | 26–33 | Scorers, rule engine, LLM reasoning (JSON mode), bidirectional enforcement, cost estimate | 0 / 8 |
| 6 — Export | 34–35 | Excel/CSV download with matches + reasoning bullets | 0 / 2 |
| 7 — Testing & Deployment | 43–47 | Unit, integration, E2E tests, Railway + Supabase production deploy | 0 / 5 |

**Total: 40 tasks** — frontend and admin panel handled separately.
