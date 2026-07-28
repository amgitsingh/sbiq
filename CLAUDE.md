# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QBCals (Quality, Boost, Calibration) — an AI-powered business event matchmaking platform. Replaces manual matchmaking with a 5-step automated pipeline: **Ingest → Normalize → Prioritize → Match → Generate**.

Built in three phases:
- **Phase 1 (MVP):** CSV ingestion, rule engine + AI matching, basic admin panel, CSV/Excel export
- **Phase 2 (Growth):** Participant/Organizer/Sponsor portals + mobile apps, email delivery, Eventbrite API sync
- **Phase 3 (Scale):** Analytics, CRM integrations, PDF reports, GDPR hardening

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python + FastAPI |
| Structured DB | SQLite (local dev) → Supabase PostgreSQL (production) |
| Vector DB | Supabase pgvector (same instance as structured DB) |
| Embeddings | OpenAI text-embedding-3-small |
| LLM / AI Engine | OpenAI-compatible API — model-agnostic, swap via config |
| Web scraping | Playwright + BeautifulSoup (company website, LinkedIn) |
| Search enrichment | Tavily API (web search + news mode) |
| Company data | Crunchbase API |
| Admin Frontend | Next.js + Tailwind CSS |
| Participant Portal | Next.js (Phase 2) |
| Email | SendGrid or Resend |
| Auth | Supabase Auth (magic link + OTP) |
| Ingestion | openpyxl + custom header mapper |
| Hosting | Vercel (frontend) + Railway/Render (backend) |

## Repository Structure (target)

```
SBIQ/
  backend/
    app/
      models/        # SQLAlchemy ORM models (Event, Participant, Match)
      routers/       # FastAPI route handlers (events, participants, matching, export)
      services/
        ingestion.py     # CSV/Excel parsing, header mapping, normalization
        rule_engine.py   # Layer 1: fast candidate pre-filter
        ai_engine.py     # Layer 2: LLM reasoning and match selection
        exporter.py      # Excel/CSV output generation
      core/
        config.py        # Settings loaded from .env
        database.py      # SQLAlchemy session + engine setup
    main.py
    requirements.txt
  frontend/
    # Next.js admin panel (Phase 1 M1.4+)
  .env.example
  QBcals.pdf         # Original product specification
```

## Development Commands

```bash
# Backend setup
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Run a specific test
pytest tests/test_rule_engine.py -v

# Run all tests
pytest

# Frontend setup (Phase 1.4+)
cd frontend
npm install
npm run dev
```

## Core Architecture: 4-Layer Matching Pipeline

This is the heart of the system. The spec PDF describes a two-layer approach; the actual implementation uses a 4-layer pipeline that adds public data enrichment and vector similarity search before the rule engine.

### Step 1 — Enrichment Pipeline (runs per participant after CSV upload)

Enrichment sources are called in this exact order and merged before the LLM normalizes them:

| Order | Source | Method |
|---|---|---|
| 1 | Company website | Playwright scrape → BeautifulSoup parse |
| 2 | Tavily web search | Tavily API (general search on company + person name) |
| 3 | News | Tavily API (news search mode) |
| 4 | Crunchbase | Crunchbase API |
| 5 | LinkedIn | Playwright scrape |

After all sources are fetched, raw data is merged and sent to the LLM which returns a **structured JSON profile**:
```json
{
  "person": {
    "name": "...",
    "designation": "...",
    "looking_for": "...",
    "offerings": "..."
  },
  "company": {
    "name": "...",
    "website": "...",
    "industry": "...",
    "products": [],
    "services": [],
    "markets": [],
    "customers": [],
    "technologies": [],
    "employee_count": "...",
    "headquarters": "...",
    "funding_stage": "...",
    "investors": [],
    "recent_news": [],
    "summary": "..."
  }
}
```

**Enrichment source → field mapping:**

| Field | Primary Source | Fallback |
|---|---|---|
| `person.name`, `person.designation` | Excel | LinkedIn |
| `person.looking_for`, `person.offerings` | Excel | LLM inference from all sources |
| `company.website` | Excel | Tavily search |
| `company.industry`, `company.products`, `company.services` | Company website | Tavily / Crunchbase |
| `company.markets`, `company.customers`, `company.technologies` | Company website | Tavily |
| `company.employee_count`, `company.headquarters` | Crunchbase | LinkedIn / company website |
| `company.funding_stage`, `company.investors` | Crunchbase | News / Tavily |
| `company.recent_news` | Tavily news search | News API |
| `company.summary` | LLM — synthesized from all sources | — |

### Step 2 — Embed + Store in pgvector
The structured JSON profile is serialized to text and embedded using **OpenAI text-embedding-3-small**. The embedding + full structured profile is stored in Supabase pgvector. No separate vector DB — pgvector runs inside the same Supabase PostgreSQL instance.

### Step 3 — Vector Similarity Search
For each participant, cosine similarity search against all other participants in the same event produces an initial candidate pool. This handles semantic matching that keyword overlap cannot (e.g., "fintech" ↔ "financial technology", "Series A investor" ↔ "early-stage funding").

### Step 4 — Rule Engine Filter
Deterministic scoring on top of similarity results narrows to **5–10 candidates**:
- Token overlap: `looking_for` ↔ `offers`
- Sector alignment score
- Company size compatibility ratio
- Ecosystem-role adjacency: is each participant's classified role (Direct Buyer/Seller, Investor, Corporate Entry Point, etc. — see `docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md`, Item 2) complementary to the other's, not just similar — the dominant factor in the composite, since pure similarity was empirically shown to miss valuable but dissimilar pairs
- Decision authority score: seniority of `designation` (e.g. CEO/Founder/Director vs. Manager)
- Duplicate pair prevention (A→B = B→A counted once)
- Priority-weighted ranking (Sponsors processed first)

### Step 5 — LLM Reasoning
Called once per participant on their 5–10 rule-engine candidates:
- Reads full enriched JSON profile + candidate shortlist
- Selects best **3–5 final matches**
- Generates reasoning bullets per match
- Writes personalized outreach email + LinkedIn intro draft

**Design principle:** Enrichment makes profiles rich enough for meaningful semantic search. Vector search handles semantic breadth cheaply at scale. The rule engine applies business logic deterministically. The LLM only sees a tiny pre-filtered set — cost stays low even for 300+ participant events.

## Priority & Eligibility Rules

| Tier | Matches Allocated | Priority Score |
|---|---|---|
| Sponsor | 3 | Highest |
| Premium Member | 2 | 100+ |
| Business Member | 1 | Standard |
| Normal Member | 1 | Standard |
| Non-member | 0 (can appear as candidate only) | Lowest |

Participants with no `looking_for` AND no `offers` text are flagged for admin review, not auto-matched.

## Data Model (core tables)

- **events** — id, name, date, description, matching_rules, status
- **participants** — id, event_id, name, company, sector, company_size, membership_tier, looking_for, offers, linkedin_url, email, status (eligible/limited/review)
- **matches** — id, event_id, participant_a_id, participant_b_id, score, reasoning_bullets (JSON), email_draft, linkedin_draft, status (pending/approved/rejected)

## CSV Ingestion Notes

- Dutch and English column headers are both valid and must be auto-mapped (e.g., `Bedrijfsnaam` → `company`)
- Sparse rows (missing `looking_for` or `offers`) are flagged, not dropped
- Membership tier is normalized from free-text (e.g., "Premium Lid" → `premium_member`)
- Supported formats: CSV, XLSX

## AI Engine Configuration

The AI client must be model-agnostic. The model, base URL, and API key are all loaded from environment config. Switching between OpenAI, Claude, or Mistral requires only a config change — no code change.

```python
# Expected .env keys
AI_API_KEY=...
AI_BASE_URL=https://api.openai.com/v1   # or Anthropic/Mistral endpoint
AI_MODEL=gpt-4o                          # or claude-sonnet-4-6, etc.
AI_MAX_TOKENS_PER_RUN=...               # cost cap
```

## Confirmed Architecture Decisions

| Decision | Choice |
|---|---|
| LinkedIn enrichment | Best-effort Playwright scrape — skip gracefully if blocked, not a hard dependency |
| Async enrichment | Celery + Redis — enrichment runs as background jobs, never blocks the request |
| Matching direction | Bidirectional — if A→B is selected, B automatically receives A; enforced at write time |
| Match quota | 3 for all tiers (flat) — tier differentiation wired in later |
| Enrichment failure | Per-source independence — if any source fails, log and proceed with partial data |
| Company enrichment | Deduplicated by domain/company name — shared across participants from same company |
| Vector search scope | Always filtered by `event_id` via WHERE clause — never cross-event |
| `looking_for` / `offerings` | Verbatim from Excel — LLM normalization must never modify these two fields |
| LLM output | JSON mode enforced — fixed schema with `matches[].participant_id`, `.rank`, `.reasoning[]`, `.email_draft`, `.linkedin_draft` |
| Cost visibility | Estimated cost shown in admin panel before triggering matching run |

## Phase Boundaries (strict)

Phase 1 features are frozen. Any new requests go to the Phase 2 backlog. Phase 1 scope:
- CSV/Excel ingestion only (no Eventbrite API — that is Phase 2)
- Admin panel only (no participant-facing portal — Phase 2)
- Export to CSV/Excel only (no email delivery — Phase 2)
- English only (multi-language is permanently out of scope)
