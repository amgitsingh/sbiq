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

> **Cross-cutting: pluggable sources (added 2026-07-15, retrofitted onto Tasks 12–14).**
> Each of the 5 enrichment sources can now be switched on/off purely via config —
> `ENABLE_WEBSITE_SCRAPER`, `ENABLE_TAVILY_WEB_SEARCH`, `ENABLE_TAVILY_NEWS_SEARCH`,
> `ENABLE_CRUNCHBASE`, `ENABLE_LINKEDIN_SCRAPER` (all default `true` except
> `ENABLE_CRUNCHBASE=false`). Implemented as a shared `@toggleable(...)` decorator
> (`app/services/enrichment/source_toggle.py`) applied to every source function — a
> disabled source returns its empty value (`None`/`[]`/`{}`) immediately, is never
> called, and no call site needs to change. Motivation: Crunchbase requires a paid API
> key that isn't available yet; this lets that source be built and merged now, "plugged
> out" until purchased, without blocking or restructuring the rest of the pipeline.

| # | Task | Description | Status |
|---|---|---|---|
| 12 | **Company website scraper** | Given a company website URL, launch a headless Playwright browser and fetch the homepage and `/about` page. Parse rendered HTML with BeautifulSoup, stripping nav, footer, and boilerplate. Return clean text capped at 5,000 characters. Handle timeouts (10s limit), 404s, and JS-heavy sites gracefully. Return `None` on any failure — never raise. | `done` |
| 13 | **Tavily web search client** | Given participant name + company name, call the Tavily Search API and return the top 5 result snippets as a combined text block. Query format: `"{person name} {company name} business"`. Cap output at 3,000 characters. Handle API errors and quota exhaustion by returning `None` gracefully. | `done` |

> **Data-quality risk observed during live testing:** a real participant search
> (`"David Bezemer" "Pensioenvisie"`) returned content entirely about an unrelated
> company — "Bezemer Group B.V.", a marine winch-rental company that happens to share
> the surname "Bezemer" — because Tavily's ranking favored the more prominent brand
> match over the actual (smaller) employer. Not a bug in Task 13's code — the
> query/cap/error-handling all worked correctly — but a real signal for **Task 19**
> (LLM normalization): the merged context must keep verbatim Excel fields (name,
> company) prominent so the LLM can recognize and discount name-collision noise from
> Tavily rather than treating it as ground truth.

| | | |  |
|---|---|---|---|
| 14 | **Tavily news search client** | Given company name, call Tavily in news search mode and return the top 5 recent news snippets. Query format: `"{company name} news funding partnership product launch"`. Cap output at 3,000 characters. Return an empty list on failure — never block the pipeline. | `done` |

> **Findings from live testing:** (1) Tavily's default `days=3` news window is too
> narrow for company enrichment — funding/partnership news doesn't land daily even for
> well-covered companies — widened to `days=90`. (2) A live test on `"Pensioenvisie"`
> confirmed a more severe version of Task 13's noise problem: **0 of 5** "news" results
> actually mentioned the company at any `days` window tested (3/30/90) — pure
> keyword-template noise, not even a name-collision like Task 13's. Added a relevance
> filter (keep only results whose title/content mentions the company name) — verified
> it correctly empties out for `Pensioenvisie` while still returning 5/5 genuine hits
> for a newsworthy company (`Microsoft`). Known limitation, left as-is: the filter is a
> substring check, so a company name appearing only in an end-of-article tag cloud
> (observed once, for `Microsoft`, low real-world impact given specific company names
> are far less likely to appear as generic tags) still counts as a "hit."

| | | |  |
|---|---|---|---|
| 15 | **Crunchbase API client** | Given company name, query the Crunchbase API for: employee count, headquarters, funding stage, funding rounds, investor names, founding year, and categories. Map the API response fields to the structured profile schema. Handle 404 (company not found) and rate limits by returning a partial dict with only the fields successfully retrieved. | `done` |

> **Built but disabled by default** (`ENABLE_CRUNCHBASE=false`, no `CRUNCHBASE_API_KEY`
> configured) — client code, error handling (404/429/network/malformed JSON), and
> field-mapping logic are complete and unit-tested against a synthetic response
> matching Crunchbase's documented v4 API shape, but **not verified against a live
> account** — no key was available to test against. Also worth reconsidering before
> purchasing: Crunchbase's coverage skews toward VC-funded startups, while the real
> sample data (`data/data.xlsx`) is almost entirely small Dutch businesses and
> self-employed consultants — a class of company Crunchbase likely has little to no
> data on, similar to the near-total miss Tavily news search hit on the same data (see
> Task 14's note). Before flipping `ENABLE_CRUNCHBASE=true`: (a) verify `FIELD_IDS` in
> `crunchbase_client.py` against Crunchbase's current API reference, and (b) confirm
> with the client whether the target audience justifies the cost.

| | | |  |
|---|---|---|---|
| 16 | **LinkedIn best-effort scraper** | Given a LinkedIn profile URL from the Excel, attempt a Playwright scrape of the public profile page. Extract: name, current title, company, and about section text. If blocked — login wall, HTTP 999, CAPTCHA, or any exception — catch it, log the reason, and return `None`. Never retry the same participant within one enrichment run. This source is entirely optional; its absence must not block the pipeline. | `done` |

> Built at `app/services/enrichment/linkedin_scraper.py`, decorated
> `@toggleable("ENABLE_LINKEDIN_SCRAPER", empty_value=None)` per the Task 12–15
> pattern. Returns `dict[str, str] | None` (keys: `name`, `title`, `company`,
> `about` — whichever were extractable) rather than a flat string, since a
> LinkedIn profile has genuinely distinct fields worth keeping separate for the
> Task 18 merger, unlike the single free-text blobs the other sources return.
> Blocked-access detection checks both the post-navigation URL (login/checkpoint/
> authwall redirects) and page title (`"Join LinkedIn"`, `"Security verification"`),
> in addition to the generic `status >= 400` check that already catches LinkedIn's
> distinctive HTTP 999 anti-scraping response. Verified live: a real public profile
> URL (`linkedin.com/in/satyanadella/`) returned HTTP 999 and was caught cleanly by
> the generic status check, confirming no special-casing was needed for that code.
> Also verified: blank URL, disabled-via-toggle, and unreachable/DNS-failure URL all
> return `None` without raising; no orphaned `chrome.exe`/headless processes remained
> after repeated calls (`browser.close()` in `finally` confirmed working, consistent
> with Task 12).

| | | |  |
|---|---|---|---|
| 17 | **Company enrichment deduplication cache** | Before running company-level enrichment (website, Tavily, news, Crunchbase), check a Redis cache keyed by `normalized_company_name:event_id`. If a cached result exists, return it immediately without making any external calls. If not cached, run enrichment and store the result with a 24-hour TTL. Person-level fields (designation, looking_for, offerings) are always taken from the participant record directly and are never cached. | `done` |

> Built as two files: `app/services/enrichment/cache.py` (a thin, generic Redis
> get/set wrapper — `redis.Redis.from_url(...)` never opens a socket at
> construction time, so only the actual GET/SET calls need try/except; a Redis
> outage logs a warning and degrades to "no cache" rather than blocking
> enrichment, consistent with every other source's never-block guarantee) and
> `app/services/enrichment/company_enrichment.py` (the orchestrator: normalizes
> the company name, builds the `company_enrichment:{event_id}:{normalized_name}`
> key, and on a miss calls all 4 company-level sources and stores the combined
> dict with a 24h TTL via `setex`).
>
> **Design resolution:** Tavily web search (Task 13) takes both a person name
> and company name, which doesn't cleanly fit "company-level, cached across
> participants" — caching a result keyed only by company would otherwise bake
> one participant's name into every colleague's cached snippet. Resolved by
> always calling `search_person_and_company(None, company_name)` from this
> cache path (company name only). This is also a straight improvement over
> Task 13's original behavior: it removes the person-name collision risk
> already flagged there (the "David Bezemer" → unrelated "Bezemer Group B.V."
> mismatch), since the query no longer contains a person's name at all.
>
> Verified live against a real Redis instance (Docker container on
> `localhost:6379`): cache miss runs all 4 sources and stores the result;
> cache hit returns the identical dict without re-invoking any source; blank/
> missing company name skips caching entirely and always runs sources
> directly (can't build a meaningful cache key); Redis made unreachable
> (bad URL) logs a warning on both GET and SETEX and falls through to running
> sources directly, confirming the cache is fully optional infrastructure.

| | | |  |
|---|---|---|---|
| 18 | **Raw enrichment data merger** | Combine outputs from all 5 enrichment sources into a single structured context string. Prefix each section clearly (e.g., `=== WEBSITE ===`, `=== TAVILY ===`, `=== NEWS ===`, `=== CRUNCHBASE ===`, `=== LINKEDIN ===`). Prepend the original Excel fields (name, designation, looking_for, offerings) verbatim at the top. This merged block is the input to the LLM normalization step. | `done` |

> Built `app/services/enrichment/merger.py` — `build_enrichment_context(...)`
> takes plain keyword args (participant fields + the Task 17 company
> enrichment dict + the Task 16 LinkedIn dict), not an ORM object, keeping this
> layer decoupled from the DB same as every other enrichment module. Empty
> sections are omitted entirely rather than kept as a "no data" placeholder —
> an absent section already reads as "unknown" to the LLM, and given how
> sparse the real sample data is (most sources return nothing for most
> participants), skipping empty sections keeps prompt size and token cost down
> for no loss of information.
>
> **Scope extension:** also folded in `ideal_connection` and
> `biggest_opportunity` — the two extra columns added in the Task 3 schema
> refinement, after CLAUDE.md's original enrichment spec was written. They're
> real free-text signal from the same Excel row with no other consumer, so
> they're included as extra participant context (non-verbatim, same as every
> enrichment section) rather than left unused.
>
> Verified with two synthetic cases: an all-sparse participant (only a website
> snippet, everything else empty/None) produces a two-section output with no
> empty headers; a fully-populated participant produces all 6 sections
> (participant + 5 sources) correctly labeled and formatted, including
> Crunchbase's dict fields and LinkedIn's dict fields each rendered as
> `Label: value` lines.

| | | |  |
|---|---|---|---|
| 19 | **LLM normalization → structured JSON profile** | Send the merged enrichment context to the LLM with JSON mode enforced. The prompt instructs the LLM to: fill all profile schema fields from available context, infer missing fields where reasonable (e.g., funding stage mentioned in a news article), write `company.summary` as a synthesis of all sources, and **never modify `person.looking_for` or `person.offerings`** — copy them verbatim from the Excel section of the context. Validate the LLM response against the profile schema and retry once on validation failure. | `done` |

> Built 3 files: `app/services/ai_client.py` (the model-agnostic LLM wrapper
> CLAUDE.md specifies — thin `openai` SDK wrapper pointed at
> `AI_BASE_URL`/`AI_API_KEY`/`AI_MODEL`, deliberately placed outside
> `enrichment/` since Task 22 embeddings and the Phase 5 reasoning step will
> reuse it too; uses portable `response_format={"type": "json_object"}` rather
> than OpenAI-only strict `json_schema` mode, to stay provider-agnostic);
> `app/services/enrichment/profile_schema.py` (Pydantic `PersonProfile` /
> `CompanyProfile` / `StructuredProfile`, mirroring CLAUDE.md's shape exactly,
> every field optional/defaulted given how sparse real participant data is);
> `app/services/enrichment/llm_normalizer.py` (`normalize_participant_profile`).
>
> **Verbatim guarantee is enforced in code, not just the prompt** — after
> schema validation, `person.looking_for`/`person.offerings` are unconditionally
> overwritten with the exact values passed in by the caller (not re-parsed out
> of the merged text), since a prompt instruction alone isn't a strong enough
> guarantee for a "confirmed architecture decision." Retry-once covers *any*
> failure in the call→parse→validate chain (bad JSON, schema mismatch, or an
> `ai_client` API error) — a transient API failure gets the same single retry a
> bad response does. A second failure raises `ProfileNormalizationError` rather
> than degrading to an empty profile, since — unlike the 5 enrichment sources —
> this step isn't optional; Task 20 should catch this specifically and mark
> that participant's `enrichment_status = failed`.
>
> **Open decision:** the per-call response token cap (`MAX_RESPONSE_TOKENS =
> 1500`) is a fixed constant, intentionally not wired to
> `AI_MAX_TOKENS_PER_RUN` — that setting is a whole-run cost cap (per
> `.env.example`), not a single-call limit. Actual run-level budget enforcement
> is still unbuilt and belongs to the "Cost visibility" architecture decision
> (a Phase 5-ish cost estimator), not this task.
>
> Verified against real OpenAI calls (`gpt-4o`, real `AI_API_KEY`) using the
> two merged contexts from the Task 18 demo run: the sparse Dutch participant
> produced a mostly-null company profile with no hallucinated fields; the
> OpenAI/Alex Smith participant produced a correctly populated profile
> (industry, employee count, recent_news, a genuine synthesized summary) with
> `looking_for`/`offerings` preserved exactly. Also verified via a monkeypatched
> `chat_json`: a first-call-bad-JSON/second-call-valid case triggers exactly
> one retry and returns the correct result; an always-failing case raises
> `ProfileNormalizationError` after exactly 2 attempts.

| | | |  |
|---|---|---|---|
| 20 | **Celery enrichment tasks** | `enrich_participant_task(participant_id)`: run all 5 enrichment sources in order → merge → LLM normalize → store the resulting structured JSON on the participant record → update each `EnrichmentJob` row with status and error if any. `batch_enrich_event_task(event_id)`: fan out `enrich_participant_task` for all participants in the event, checking the company deduplication cache before dispatching company-level calls. | `done` |

> Implemented the two `app/workers/enrichment_tasks.py` stubs (`enrich_participant`,
> `batch_enrich_event`). Added `app.core.database.session_scope()` — a
> `@contextmanager` twin of `get_db()` for Celery tasks, which can't use a FastAPI
> generator dependency. Added `EnrichmentSource.llm_normalization` so the
> normalization step's success/failure is a 6th tracked `EnrichmentJob` row, not
> just the 5 raw sources — otherwise a `ProfileNormalizationError` would be
> invisible to Task 21's status endpoint. Wired `autoretry_for=(ProfileNormalizationError,)`
> onto `enrich_participant`'s existing (previously-unused) `max_retries=3,
> default_retry_delay=60`.
>
> **Open limitation:** the 5 raw-source `EnrichmentJob` rows are always
> `status=done` — Tasks 12–16 were deliberately built to never raise (every
> failure mode already collapses to `None`/`[]`/`{}` inside each source), so this
> task genuinely cannot distinguish "toggled off" from "no data found" from "it
> errored" from here. Only the `llm_normalization` row can be `status=failed`
> with a real `error_message`, since that's the one step that raises.

> **Added outside the 40-task list:** `POST /events/{id}/enrich` (`app/routers/events.py`)
> — nothing previously called Task 20's Celery tasks, so enrichment couldn't be
> triggered except from a Python shell. Open decision: a deliberate, separate
> trigger rather than auto-firing on upload, since enrichment spends real
> Tavily/OpenAI credits and an organizer may want to fix flagged rows first.

> **Added outside the 40-task list:** LLM normalization can now search the web
> itself, via OpenAI's Responses API hosted `web_search` tool
> (`ai_client.chat_json_web_search`, one call — search + synthesis together, not
> two round trips), toggled by `ENABLE_LLM_WEB_SEARCH`. Prompted by real testing
> showing 4 of the 5 sources routinely return nothing for small companies.
> **Open decision:** this is OpenAI-specific, not portable to another
> `AI_BASE_URL` provider — turn the toggle off if one is used. Required bumping
> `openai` 1.57.0 → 1.109.1 (the old version predates the Responses API).
> Verified live: same sparse Pensioenvisie case that exposed the gap now returns
> `website`, `employee_count`, and `headquarters` that no prior source ever
> found, confirmed via an actual `web_search_call` in the response (not just
> the model's own training knowledge). Retry-once and the toggle-off fallback
> (plain `chat_json`, unchanged) both still verified working.

> **Bug found via real usage (a 17-participant run produced 228 `EnrichmentJob`
> rows instead of the expected 102):** `enrich_participant`'s Celery-level
> `autoretry_for=(ProfileNormalizationError,)` retried the *entire* task —
> re-running all 5 sources and re-writing all 6 job rows — just to retry the one
> step that had actually failed. Fixed by removing the Celery-level retry
> entirely and adding one bounded extra attempt inside the task itself
> (`_normalize_with_one_extra_retry`, 15s delay), reusing the already-built
> merged context — the 5 sources now run exactly once per participant no
> matter how many normalization attempts it takes. Verified: a
> permanently-failing case and a fails-once-then-succeeds case both end with
> exactly 6 job rows (not 12).

> **Added outside the 40-task list: cross-event enrichment reuse, keyed by
> email.** New `enriched_profiles` table (migration `0004`) + `profile_reuse.py`
> — `enrich_participant` checks this first; if the same email was enriched
> within `ENRICHMENT_REUSE_MAX_AGE_DAYS` (default 30), it reuses that profile
> instead of re-running the 5 sources + LLM (writes one `reused_from_cache`
> job row instead of 6), only overriding `looking_for`/`offerings` with this
> event's own values — those two fields are per-event answers, never reused
> even when the rest of the profile is. Toggle: `ENABLE_ENRICHMENT_REUSE`.
>
> **Bug found and fixed along the way (unrelated to reuse):** the LLM
> occasionally wraps its JSON response in a ` ```json ` markdown fence despite
> being told not to — more often observed with `ENABLE_LLM_WEB_SEARCH`'s
> Responses API path — which `json.loads` can't parse, surfacing as a
> `ProfileNormalizationError`. Fixed with `_strip_markdown_fence(...)` in
> `llm_normalizer.py` before parsing. Verified live: reuse across two events
> (zero source calls, correct per-event `looking_for`/`offerings`), a stale
> cache correctly triggering a fresh re-run and bumping `last_enriched_at`,
> and `ENABLE_ENRICHMENT_REUSE=false` bypassing the check entirely.

| | | |  |
|---|---|---|---|
| 21 | **Enrichment status API endpoint** | `GET /events/{id}/enrichment-status` — return per-participant enrichment status (pending / enriching / done / failed) with a per-source breakdown for each participant. Include aggregate counts: total participants, enriched, failed, and pending. Used by the frontend to poll enrichment progress in real time. | `done` |

---

## Phase 4 — Embedding & Vector Storage
> Convert each enriched profile into a vector and store it in pgvector for similarity search.

| # | Task | Description | Status |
|---|---|---|---|
| 22 | **Embedding generation service** | Serialize the structured JSON profile to a flat text string (person fields first, then company fields, in a consistent format). Call the OpenAI `text-embedding-3-small` API to get a 1536-dimension vector. Handle API errors with one retry. Log token count per call to support cost tracking. | `done` |
| 23 | **pgvector upsert service** | Store or update a participant's embedding in the `participant_embeddings` table. Upsert on `(participant_id, event_id)`. Store the embedding vector alongside a snapshot of the structured profile JSON for debugging. Called automatically after LLM normalization completes for each participant. | `done` |
| 24 | **Event-scoped cosine similarity search** | Given a `participant_id` and `event_id`: fetch the participant's embedding, run a pgvector cosine similarity query with a hard `WHERE event_id = ?` filter — never search across events. Exclude the participant themselves from results. Return the top N candidates (configurable, default 20) with their similarity scores. Output feeds directly into the rule engine. | `done` |
| 25 | **POST /events/{id}/embed endpoint** | Trigger embedding generation for all enriched participants in an event. Skip any participant whose `enrichment_status` is not `done`. Enqueue embedding jobs as Celery tasks. Return the number of jobs enqueued and an estimated completion time. Callable only after enrichment is complete. | `done` |

> Task 22 built `app/services/embedding.py` (`serialize_profile_to_text`,
> `generate_embedding`) plus a thin `embed_text` wrapper in `ai_client.py` —
> same split as Task 19's normalizer/ai_client pair, so the retry loop lives
> with the caller, not the API wrapper. Placed outside `enrichment/` per the
> Task 19 note, since embedding is its own pipeline stage. `participant_embeddings`
> table already existed from an earlier migration (0002) — Task 23 just needs
> to write to it. Live-verified against the real OpenAI embeddings API (1536-dim
> vector, real token counts) and against a simulated failure (confirms retry-once-
> then-raise).
>
> Task 23 built `app/services/embedding_store.py` (`upsert_participant_embedding`)
> and wired it into `enrich_participant` right after `structured_profile` is set,
> on both the fresh-enrichment and cache-reuse paths — embeddings are scoped to
> `(participant_id, event_id)`, never reused cross-event, since `looking_for`/
> `offerings` (and therefore the embedded text) are per-event even when the rest
> of the profile is reused. Embedding failure is caught and logged, not raised —
> it doesn't invalidate an otherwise-successful enrichment; Task 25's endpoint is
> the recovery path for a missing embedding. Live-verified end-to-end through the
> real Celery task (not mocked): fresh path produces a correct embedding scoped
> to its event; reuse path (same email, second event) confirmed to produce a
> different embedding reflecting that event's own looking_for/offerings, not a
> copy of the first event's.
>
> Task 24 built `app/services/similarity_search.py` (`find_similar_participants`),
> using pgvector-python's `Vector.cosine_distance()` comparator (backs onto the
> existing HNSW index from migration 0002 — `ORDER BY distance LIMIT N` lets
> Postgres use it directly rather than pulling every row into Python). Similarity
> score = `1 - cosine_distance`. Live-verified with 3 real embedded profiles in
> one event (fintech investor, fintech VC, gardening supplier) — the VC correctly
> ranked far above the gardening supplier, the participant excluded themselves,
> `top_n` limiting worked, and a 4th participant with byte-identical profile
> content but in a different event never appeared in the results (event_id
> filter holds even when nothing else distinguishes the rows). A participant
> with no embedding yet returns `[]` rather than erroring.
>
> Task 25 built `app/workers/embedding_tasks.py` (`embed_participant`,
> `batch_embed_event`) plus the `POST /events/{id}/embed` route — the manual/
> backfill counterpart to Task 23's automatic embedding: re-embeds an
> already-enriched participant's existing `structured_profile` without
> re-running enrichment. Endpoint rejects (400) while any participant is still
> `pending`/`enriching`, and rejects an event with zero participants; skips
> non-`done` participants when dispatching. Live-verified through the real
> Celery worker + FastAPI server: 400 while a participant was still `pending`,
> then a real 202 dispatch + successful OpenAI embedding call once that
> participant reached a terminal (`failed`) state, confirmed via the
> `participant_embeddings` row it wrote.

---

## Phase 5 — Matching Engine
> Filter similarity search results through deterministic scoring, then use the LLM to select and justify the final matches.

| # | Task | Description | Status |
|---|---|---|---|
| 26 | **Token overlap scorer** | Tokenize and normalize (lowercase, remove stopwords) the `looking_for` and `offerings` fields. Score a candidate pair A↔B as: `overlap(A.looking_for, B.offerings) + overlap(B.looking_for, A.offerings)`. Return a float 0–1. This is the primary intent-alignment signal in the rule engine. | `done` |
| 27 | **Sector alignment + company size scorers** | Sector scorer: exact industry match = 1.0, adjacent sector (predefined adjacency map, e.g., fintech ↔ banking) = 0.5, unrelated = 0.0. Company size scorer: same bucket = 1.0, one bucket apart = 0.5, two or more apart = 0.0. Size buckets: 1–10, 11–50, 51–200, 201–1000, 1000+. Both return float 0–1. | `done` |
| 28 | **Rule engine** | For each participant, take their similarity search candidates and apply composite scoring: `score = (token_overlap × 0.5) + (sector × 0.3) + (size × 0.2)`. Hard exclusions: same-company pairs (matched by normalized company name). Global deduplication: track all seen pairs in a set so A→B and B→A are not both processed. Return the top 5–10 ranked candidates per participant. Process sponsors first, then premium members, then others — so the best candidates are allocated to higher-priority participants first. | `done` |
| 29 | **LLM matching reasoning service** | Send a participant's full structured JSON profile along with their 5–10 rule engine candidates to the LLM with JSON mode enforced. The prompt instructs the LLM to select the best 3–5 matches and return a structured response: `matches[].participant_id`, `matches[].rank`, `matches[].reasoning` (array of 3 bullet strings), `matches[].email_draft`, `matches[].linkedin_draft`. Validate the response schema. Retry once on invalid schema. Log input and output token counts per call. | `done` |
| 30 | **Bidirectional match enforcement** | After the LLM selects A→B: check if a match record from B to A already exists. If not, create the reverse record B→A with `is_bidirectional = True` and the same reasoning mirrored. Prevents duplicate pair creation in the case where both A and B independently selected each other through their own matching runs. | `done` |
| 31 | **Pre-run cost estimator** | Before any matching run: count enriched participants in the event. Estimate embedding token cost (avg profile character length × participant count, converted to tokens, priced against `text-embedding-3-small` rate). Estimate LLM reasoning token cost (avg prompt size with candidates × participant count, priced against the configured model rate). Return a breakdown: embedding cost, LLM cost, total in USD. | `done` |
| 32 | **Celery matching tasks** | `match_participant_task(participant_id, event_id)`: run similarity search → rule engine → LLM reasoning → store match records → enforce bidirectional. `batch_match_event_task(event_id)`: fan out `match_participant_task` for all embedded participants in the event, respecting tier-based processing order (sponsors dispatched first). Track matching progress per participant. | `done` |
| 33 | **POST /events/{id}/match endpoint** | Trigger the matching run for an event. Validate that all participants have been embedded. Return the cost estimate and require a `confirm=true` query parameter to actually enqueue the batch job — prevents accidental runs. Enqueue `batch_match_event_task`. Return a job ID and estimated duration. | `done` |

> Task 26 built `app/services/matching/token_overlap.py` (`tokenize`,
> `token_overlap_score`) - new `matching/` subpackage mirroring `enrichment/`'s
> convention, since Phase 5 has several related scorer files ahead (Task 27,
> then Task 28 combining them). Overlap uses the Szymkiewicz-Simpson
> coefficient (`|intersection| / min(|A|,|B|)`) rather than Jaccard, since
> `looking_for`/`offerings` are often very different lengths and overlap
> coefficient asks "how much of the shorter phrase is covered" rather than
> penalizing for the longer phrase's extra words. The two directional overlaps
> are averaged, not summed, to keep the final score in the spec's required
> [0, 1] range - a straight sum of two [0, 1] values could reach 2. Live-verified:
> exact reciprocal match scores 1.0, no overlap scores 0.0, a one-directional-only
> match scores half of a bidirectional one (not double-counted), empty/None
> fields don't crash, and Dutch text (untranslated, per the English-only phase
> boundary) tokenizes and matches correctly since no language-specific logic is
> involved.
>
> Task 27 built `app/services/matching/sector_size.py`
> (`sector_alignment_score`, `company_size_score`). Checked real sample data
> (`data/data.xlsx`) before writing this - both `sector` and `company_size` are
> raw free text with no controlled vocabulary (e.g. sector: "Banking /
> occupational health and absenteeism"; size: "4400 +", "1 - 10 FTE", "x",
> "I am bringing a guest"), not the clean bucketed values the task description
> implies. Sector: keyword-based classifier maps free text into zero or more
> of ~18 canonical categories (a raw string can be genuinely multi-topic, e.g.
> the banking/health example above classifies as both); exact-category-overlap
> wins over adjacency, which is checked via a symmetric adjacency map built
> from a flat pair list (avoids the bug class where an edit adds A→B but
> forgets B→A). Company size: regex-extracts numbers from free text (handles
> commas, decimals, "+"/"FTE" suffixes, and 2-number ranges via averaging),
> unparseable garbage returns `None` and scores 0.0 rather than crashing or
> guessing. Live-verified: all 16 unique real `sector` values and 17 unique
> real `company_size` values from the sample file classify/parse sensibly;
> exact/adjacent/unrelated/garbage scoring cases all confirmed correct for
> both scorers.
>
> Task 28 built `app/services/matching/rule_engine.py` (`score_pair`,
> `rank_candidates`, `run_rule_engine_for_event`). Pulled in two rules from
> CLAUDE.md's Priority & Eligibility Rules table that the task description
> itself doesn't mention but that belong at exactly this layer: non-members
> (0 matches allocated) and review-flagged participants (blank
> looking_for/offerings, "not auto-matched") never get a shortlist generated
> *for* them, but both are still eligible to appear *in* other participants'
> shortlists - a review-flagged participant's blank fields already zero out
> their token-overlap contribution naturally, so no extra filtering was needed
> there, just the exclusion from being a primary subject. "A→B = B→A counted
> once" is implemented as a computation cache (`pair_cache`, keyed by
> `frozenset`) rather than a result exclusion, since `score_pair` is fully
> symmetric and the same pair can legitimately appear in both participants'
> shortlists - it's the score computation that's deduplicated, not the
> listing. Live-verified with 7 participants across all 5 tiers (including a
> same-company pair and a fintech-relevant non-member): non-member and
> review-flagged participants correctly got no shortlist of their own while
> still appearing as candidates for others (the non-member ranked #1 for both
> the sponsor and premium fintech participants); same-company pair excluded
> each other bidirectionally; cached pair scores confirmed symmetric
> (Sponsor→Premium and Premium→Sponsor both scored 0.487).
>
> Task 29 built `app/services/matching/match_schema.py` (`MatchItem`,
> `MatchSelection`) and `app/services/matching/llm_matcher.py`
> (`select_matches`, `build_matching_prompt`) - same retry-once/schema-validate
> shape as Task 19's normalizer. Extracted the markdown-fence-stripping helper
> (previously local to `llm_normalizer.py`) into a shared
> `app/services/json_utils.py`, since it's now needed in two places. Added
> `chat_json_with_usage` to `ai_client.py` alongside the existing `chat_json` -
> a separate function rather than changing `chat_json`'s return shape, so
> `llm_normalizer.py` (which doesn't need token logging) is untouched.
> Validation goes beyond Pydantic's shape check into business rules the schema
> alone can't express: `participant_id` must be one of the given candidate
> IDs (LLM must never invent one), no duplicate participant_id or rank, ranks
> must form a contiguous 1..N sequence, and reasoning must be exactly 3
> bullets - any violation counts as a failed attempt and triggers the same
> retry-once-then-raise as a JSON parse failure. Returns `[]` immediately with
> no LLM call when given zero candidates. Live-verified against the real
> OpenAI API with a realistic 3-candidate shortlist (two strong fintech
> matches, one irrelevant gardening company): correctly matched the top
> fintech candidate with concrete, profile-grounded reasoning and skipped the
> gardening one entirely, with real token counts logged. Also verified the
> retry-then-raise path with a simulated hallucinated `participant_id`.
>
> Task 30 built `app/services/matching/match_writer.py` (`store_match`) - the
> first Phase 5 task that actually writes to the `matches` table (Tasks
> 26-29 were pure computation). Upserts on the ordered `(event_id,
> participant_a_id, participant_b_id)` triple so a participant's matching run
> can be safely re-run without duplicating rows, not just a plain insert.
> `email_draft`/`linkedin_draft` are deliberately *not* mirrored onto the
> auto-created reverse record (only `reasoning`, `rank`, and `score` are) -
> drafts are personalized and directional (A's outreach *to* B), so copying
> them onto B→A would put A's words in B's mouth; a genuine pair fills in
> later if B's own run independently selects A. When that happens, the
> existing placeholder is updated in place (content replaced,
> `is_bidirectional` flipped back to `False` since it's no longer a mere
> mirror) rather than creating a second row - this is the "A→B = B→A counted
> once" duplicate prevention. Live-verified all three cases against the real
> DB: a genuine A→B store correctly creates both the genuine row and a null-
> draft mirrored placeholder; a later genuine B→A store from B's own run
> upgrades that placeholder in place (content replaced, flag flipped) without
> touching A→B's original row or creating a 3rd row; and re-running A→B's own
> store again updates in place rather than duplicating - 2 rows in the table
> throughout all three steps.
>
> Task 31 built `app/services/matching/cost_estimator.py`
> (`estimate_matching_run_cost`). Character lengths come from each
> participant's real stored `structured_profile`, serialized with the exact
> same `serialize_profile_to_text` used for real embedding input (Task 22) -
> not a synthetic guess. Two participant counts, not one: embedding cost is
> priced against every enriched participant (Task 23 embeds all of them
> unconditionally), while LLM cost is priced only against participants who'll
> actually get a rule-engine shortlist and an LLM call - excludes non-members
> and review-flagged participants, mirroring Task 28's own filtering exactly,
> so the estimate doesn't overstate cost for people who will never trigger a
> match run. Prompt-size estimate uses 10 candidates per participant (the top
> of the rule engine's 5-10 range) so the estimate errs high, never low, per
> the same cost-guardrail spirit as `AI_MAX_TOKENS_PER_RUN`. LLM pricing is a
> small table keyed by substring match against `AI_MODEL` (gpt-4o/mini,
> gpt-4-turbo, gpt-3.5, falling back to gpt-4o-equivalent pricing for an
> unrecognized model) - needs a manual update if `AI_MODEL` changes to
> something not listed, noted for `CONFIG_CAVEATS.md`. No tiktoken dependency;
> uses a ~4-chars/token heuristic, which matches this task's own "avg
> character length" framing and is precise enough for a pre-run guardrail, not
> a real bill. Live-verified: a realistic 6-participant mix (all 5 tiers plus
> a review-flagged one) correctly counted 6 for embedding but only 4 for LLM
> (excluding the non-member and the review-flagged participant); zero-
> participant event returns clean zeros without crashing; a 300-participant
> scale test (CLAUDE.md's stated target size) came out under $3 total,
> confirming the "cost stays low even for 300+ participant events" design
> principle actually holds with real numbers.

---

> Task 32 built `app/workers/matching_tasks.py` (`match_participant`,
> `batch_match_event`), wiring together every Phase 5 building block so far
> (Tasks 24, 28, 29, 30). Added a new `matching_status` column on
> `Participant` (migration `0005`), mirroring `enrichment_status` exactly
> (pending/matching/done/failed) - the task description's "track matching
> progress per participant" reads as the same tracking mechanism already
> established for enrichment, not a new concept. `batch_match_event` requires
> an actual `participant_embeddings` row (join, not just
> `enrichment_status=done`) before dispatching - a participant can be
> enrichment-done with no embedding yet if Task 23's automatic attempt failed
> silently. No Celery-level autoretry on `match_participant` - `select_matches`
> already retries once internally, and a full-task retry on top of that would
> risk paying for a second LLM call for no benefit, same lesson as the
> enrichment retry-storm bug. Non-member/review-flagged exclusion is enforced
> twice - once in `batch_match_event`'s dispatch query, and again defensively
> inside `match_participant` itself in case it's ever invoked directly.
> Live-verified through the real Celery worker on the `matching` queue (the
> startup banner's queue binding line looked suspicious -
> "exchange=enrichment(direct) key=enrichment" for the `matching` queue -
> but an empirical dispatch-and-consume test confirmed routing is actually
> correct; cosmetic banner quirk, not a bug) with 5 real participants across
> 4 tiers: the non-member was correctly never dispatched (stayed
> `matching_status=pending`) while still surfacing as a real LLM-selected
> candidate for two other participants; and two participants independently
> selected each other in separate task runs, which correctly upgraded the
> auto-mirrored placeholder into a genuine bidirectional pair in place (both
> `is_bidirectional=False`, both with real drafts) rather than duplicating -
> exactly 2 rows for that pair throughout.

> Task 33 added `POST /events/{id}/match` to `events.py`. Gates on the same
> "not embedded yet" check as the reasoning behind `/embed`'s own gate, but
> phrased as a hard reject naming the shortfall count, since matching without
> embeddings would silently produce empty candidate pools rather than an
> obvious error. Dispatches `batch_match_event` asynchronously via `.delay()`
> and returns its real Celery task ID as `job_id` - a deliberate difference
> from `/enrich` and `/embed`, which call their batch task directly and
> return an immediate count instead; Task 33 explicitly asks for a job ID
> back, which only a real async dispatch can honestly provide. Cost-gate
> works as two calls to the same endpoint: without `?confirm=true` it's HTTP
> 200 with just the cost breakdown and nothing dispatched (`job_id: null`);
> with it, HTTP 202, a real dispatch, and a job ID. Live-verified through the
> real API end-to-end: 400 for zero participants, 400 for enriched-but-not-
> embedded (naming the count), a real embed run to clear that gate, 200/
> preview mode with no dispatch, then 202/confirmed mode whose returned
> `job_id` was confirmed to be the exact Celery task ID the worker log showed
> processing - and the run itself produced a genuine mutual match between the
> two test participants (both directions independently selected, both
> `is_bidirectional=False`), consistent with Task 30's verified behavior.

Phase 5 (Matching Engine) is now fully built: similarity search -> rule
engine -> LLM reasoning -> bidirectional match storage -> cost-gated trigger,
all live-verified against real Postgres, Redis, OpenAI, and Celery - nothing
in this phase was verified against mocks alone.

> **Added outside the 40-task list: ecosystem-role adjacency + decision
> authority in the rule-engine pre-filter** (see
> `docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md`, Item 2, and
> `docs/PREFILTER_COST_ANALYSIS.md`). A prior attempt fixed only the final
> scoring formula while leaving the existing similarity-based pre-filter
> (vector search + token-overlap/sector/size rule engine) untouched, and was
> reverted after proving empirically that a client-approved reference run's
> real matches for two real participants never survive that pre-filter at
> all - both scored near-zero on every existing dimension, regardless of
> pool size. Root cause: the pre-filter only measures similarity, and the
> client's own methodology (docx, "Proposed SBIQ Rule") explicitly argues
> similarity is often the wrong signal - a participant's *ecosystem role*
> (Direct Buyer, Investor, Corporate Entry Point, etc. - an 11-item taxonomy
> taken verbatim from the docx) and whether two roles are *complementary*
> matters more than whether two profiles read alike. New
> `app/services/matching/ecosystem_role.py` classifies each participant into
> one of the 11 roles (added to the existing per-participant enrichment LLM
> call in `llm_normalizer.py` - no new LLM call, ~10-20 extra output tokens)
> and scores role-adjacency via a static lookup table (same pattern as the
> existing `SECTOR_ADJACENCY`) - deliberately binary and never rewarding
> identical roles, since two participants competing for the same
> counterparts isn't a complementary match. `decision_authority.py`
> (seniority of `designation`) was also re-added. Both are cheap, O(1)-per-
> pair signals - no LLM call per candidate pair, so this avoids the O(N²)
> cost blowout of simply removing the pre-filter (quantified in
> `docs/PREFILTER_COST_ANALYSIS.md`). Rule-engine composite weights
> rebalanced: role adjacency 0.40 (now the dominant factor), token overlap
> 0.25, sector 0.15, size 0.10, decision authority 0.10. Scope deliberately
> narrow - `llm_matcher.py`, `match_schema.py`, `match_writer.py`, the
> `Match` model, and `matching_tasks.py` are all untouched; `Match.score`
> stays exactly the rule engine's composite, same as before. This pass is
> only about getting the right candidates into the LLM's shortlist in the
> first place.

---

## Phase 6 — Match Output
> Original scope (Excel/CSV export, openpyxl) descoped per explicit direction -
> no file export needed. Replaced with a single paginated read API over the
> `matches` table instead.

| # | Task | Description | Status |
|---|---|---|---|
| 34 | ~~Excel/CSV export formatter~~ | Descoped - not needed. | `cancelled` |
| 35 | **GET /events/{id}/matches endpoint** | Paginated read of all match pairs for an event (`limit`/`offset`, default 50, max 200 per page), one row per pair - A→B and B→A are deduplicated to a single row, not returned as two. No status filter - returns every pair regardless of `MatchStatus`. Each row includes both participants (id/name/email/company), rank, score, reasoning bullets, email/LinkedIn drafts, status, and `mutual`. Ordered by `id` for stable pagination. | `done` |

> First cut returned both directions of a bidirectional pair as separate rows
> (A→B and B→A) - corrected after live user testing surfaced it as an
> unwanted near-duplicate, not a useful distinction. Now deduplicated per
> unordered pair: the genuine (real reasoning/drafts) row always wins over an
> auto-mirrored placeholder (Task 30's placeholders are never anyone's own
> real selection); where *both* directions are genuine (each side
> independently selected the other), the lower id wins, purely for
> deterministic output. `is_bidirectional` was replaced with `mutual` in the
> response - the old field stopped being meaningful once every returned row
> is guaranteed genuine (`is_bidirectional=False`); `mutual` instead answers
> "did both sides pick this pair independently", which is real information
> the dedup would otherwise silently discard. Built with `joinedload` on both
> participant relationships to avoid N+1 queries; dedup happens in Python
> after fetching all of an event's matches (not at the DB layer), since a
> pair's two rows must be compared against each other before paging, not
> within one page. Live-verified against a real 4-row dataset (one mutual
> pair, one one-sided pair with a placeholder): correctly collapsed to 2
> pairs, mutual pair flagged `mutual=true`, one-sided pair kept the genuine
> row and dropped the null-draft placeholder; `limit`/`offset` paging
> reconfirmed correct over the deduplicated set; 400s reconfirmed for
> `limit=0`, `limit=500` (over the 200 cap), and `offset=-1`.

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
| 3 — Enrichment Pipeline | 12–21 | 5 enrichment sources, dedup cache, merger, LLM normalization, async Celery jobs | 10 / 10 |
| 4 — Embedding & Vector Storage | 22–25 | Embedding generation, pgvector upsert, event-scoped similarity search | 4 / 4 |
| 5 — Matching Engine | 26–33 | Scorers, rule engine, LLM reasoning (JSON mode), bidirectional enforcement, cost estimate | 8 / 8 |
| 6 — Match Output | 34–35 | Paginated GET /matches API (Excel/CSV export descoped) | 1 / 2 (1 cancelled) |
| 7 — Testing & Deployment | 43–47 | Unit, integration, E2E tests, Railway + Supabase production deploy | 0 / 5 |

**Total: 40 tasks** — frontend and admin panel handled separately.
