# Configuration Caveats

Non-obvious coupling and side effects to check before changing any `.env` value or
`app/core/config.py` setting. Grouped by area. If you add a new setting with a
similar hidden dependency, add it here.

## AI / LLM (`AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, `AI_EMBEDDING_MODEL`, `AI_MAX_TOKENS_PER_RUN`, `ENABLE_LLM_WEB_SEARCH`)

- **`AI_BASE_URL` is not fully provider-agnostic in practice, despite the
  model-agnostic design goal.** Swapping it to an Anthropic/Mistral-compatible
  endpoint breaks `ENABLE_LLM_WEB_SEARCH` outright — that feature calls OpenAI's
  Responses API hosted `web_search` tool (`ai_client.chat_json_web_search`), which
  is OpenAI-specific, not a generic "OpenAI-compatible" capability. **Turn
  `ENABLE_LLM_WEB_SEARCH=false` before pointing `AI_BASE_URL` anywhere else.** The
  plain `ai_client.chat_json` path (used everywhere `ENABLE_LLM_WEB_SEARCH=false`,
  and by any future non-search caller) is the only genuinely portable path — even
  that assumes the target endpoint supports `response_format={"type":
  "json_object"}`, which isn't universal across "OpenAI-compatible" proxies either;
  verify before relying on it.
- **`AI_MODEL` must support whatever path is active.** With
  `ENABLE_LLM_WEB_SEARCH=true`, the model must work with the Responses API + hosted
  `web_search` tool. With it `false`, the model just needs
  `response_format={"type": "json_object"}` support in Chat Completions. Not every
  model supports both — changing `AI_MODEL` without checking which path is enabled
  can silently break normalization (surfaces as a `ProfileNormalizationError` after
  2 failed attempts, not an obvious config error).
- **`AI_MAX_TOKENS_PER_RUN` currently does nothing.** It's documented as a
  whole-run cost cap, but no budget-tracking/enforcement code exists yet (that's a
  future cost-estimator task). Changing this value has zero effect on running
  behavior today — don't mistake it for a working throttle.
- **The per-call token cap is a separate, hardcoded constant, not an env var.**
  `llm_normalizer.MAX_RESPONSE_TOKENS = 1_500` controls the actual per-call limit
  for normalization; it is not sourced from `.env`. Changing `AI_MAX_TOKENS_PER_RUN`
  will not touch it.
- **`openai` SDK version matters.** `ENABLE_LLM_WEB_SEARCH` requires
  `client.responses` to exist — added well after `1.57.0` (originally pinned;
  bumped to `1.109.1`). Downgrading the `openai` package would silently break this
  feature with an `AttributeError`, not a config error.

## Enrichment source toggles (`ENABLE_WEBSITE_SCRAPER`, `ENABLE_TAVILY_WEB_SEARCH`, `ENABLE_TAVILY_NEWS_SEARCH`, `ENABLE_CRUNCHBASE`, `ENABLE_LINKEDIN_SCRAPER`)

- **Disabling a source doesn't just skip it — it returns a specific typed empty
  value** (`None`/`[]`/`{}`, set per-source via `@toggleable(..., empty_value=...)`
  in `source_toggle.py`). `merger.py` and `company_enrichment.py` both depend on
  these exact empty-value types (e.g. `if website := ...` truthiness checks). A new
  source added without matching this convention could silently break the merger's
  "omit empty sections" logic.
- **`ENABLE_CRUNCHBASE=true` needs `CRUNCHBASE_API_KEY` set, and the field mapping
  in `crunchbase_client.py` (`FIELD_IDS`, `_map_entity`) was never verified against
  a live account** (Task 15 — built against documented API shape only, no key was
  available). Verify the current Crunchbase v4 API schema before flipping this on
  in production.
- **`ENABLE_LINKEDIN_SCRAPER=true` requires Playwright browser binaries installed**
  (`playwright install chromium`). If they're missing, every call fails and
  degrades to `None` — which looks identical to "LinkedIn blocked us" in the logs.
  This is a real diagnostic trap: a missing binary and a genuine block are
  indistinguishable from the enrichment output alone.

## Database (`DATABASE_URL`)

- **A `DATABASE_URL` with no database name silently connects to a same-named
  default database, not an error.** We hit this for real: `.env` had
  `postgresql://postgres:postgres@localhost` (no `/qbcals`), which connected fine —
  just to the wrong database (a completely unrelated project's schema sitting on
  the same Postgres server). Always confirm the database name in the URL, and
  ideally confirm the connected DB has the expected tables
  (`events`/`participants`/`matches`/`enrichment_jobs`/`participant_embeddings`)
  before running migrations or writes against it.
- **`.env` must live at `backend/.env`, not the project root.**
  `Settings.model_config = SettingsConfigDict(env_file=".env")` resolves relative
  to the process's current working directory, which is `backend/` for every
  documented run/test command. A root-level `.env` is silently ignored — no error,
  just empty defaults.

## Redis / Celery (`REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`)

- **These three are independent, not aliases of each other**, even though they
  default to the same host. `REDIS_URL` backs the Task 17 company-enrichment dedup
  cache (`cache.py`) only. `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` back Celery's
  queue and result store. Moving to a new Redis instance requires updating all
  three consistently — changing only one leaves the others pointed at the old
  instance with no error, just quietly-wrong behavior (e.g. cache hits that should
  no longer exist, or Celery unable to reach its broker while the cache works
  fine).
- **Redis being down affects different parts of the system differently.** The
  dedup cache degrades gracefully (`cache.py` catches every Redis error, falls back
  to "no cache"). Celery itself has no such fallback — if the broker is
  unreachable, task dispatch fails outright. Don't assume "Redis is optional" as a
  blanket statement.
- **Celery task registration relies on explicit imports, not
  `autodiscover_tasks()`.** `autodiscover_tasks(["app.workers"])` only looks for a
  submodule literally named `tasks.py` (Celery's Django-style convention) — our
  files are `enrichment_tasks.py`/`matching_tasks.py`, so autodiscovery silently
  registered nothing (a real bug, caught only once a live worker was actually run).
  Fixed via explicit `from app.workers import enrichment_tasks, matching_tasks` at
  the bottom of `celery_app.py`. **Any new task module added in the future must
  also be explicitly imported there** — it will not be picked up automatically.
- **`task_routes` in `celery_app.py` matches by module path string**
  (`"app.workers.enrichment_tasks.*"`). Renaming or relocating a task module breaks
  its queue routing silently — the task falls back to `task_default_queue`
  (`"enrichment"`) rather than raising an error.
- **On Windows, a local worker needs `--pool=solo`** (Celery's default prefork pool
  doesn't work reliably on Windows). This processes one task at a time — fine for
  local testing, but don't carry `--pool=solo` into the production deployment
  (Linux, per CLAUDE.md), which should use the default pool for real concurrency.

## Enum columns (`native_enum=False`)

- **Every `Enum(...)` model column uses `native_enum=False`, meaning the DB column
  is plain `VARCHAR` with no schema-level enforcement.** Adding a new enum member
  (like `EnrichmentSource.llm_normalization`) needs no migration — it's just a new
  valid string. But **renaming or removing an existing member is a breaking change
  for any historical row already storing the old string** — those rows will fail
  Python-side enum parsing on read, since nothing at the DB layer prevents or
  flags the mismatch.

## Supabase (`SUPABASE_URL`, `SUPABASE_KEY`)

- **Configured but not wired to anything yet.** The actual DB connection today is
  entirely governed by `DATABASE_URL` (local Postgres). Setting these two env vars
  alone has no effect until a Supabase-specific integration is built — don't assume
  the app switches to Supabase just because these are filled in.
