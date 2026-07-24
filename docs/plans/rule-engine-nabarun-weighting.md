# Rewrite matching score around Nabarun's 8-factor weighted formula

> **Status: proposed, not yet implemented.** Saved here for later — see the
> conversation that produced it for full context if needed.

## Context

The client-approved reference run from Nabarun (`nabarun_response.json`) scores
every candidate pair on 8 weighted factors (commercial fit 0.34, sector 0.16,
strategic value 0.14, growth/revenue 0.14, size 0.07, decision authority 0.06,
brand/network 0.05, feasibility 0.04) rather than our current 3-factor
similarity formula (token overlap 0.5, sector 0.3, size 0.2). We already have
concrete evidence (`docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md`, Item 2) that our
current formula produces materially worse matches than Nabarun's approved run
for the same real participants (e.g. Edwin Groenewoud/Temis Luxury, Britt
Bleeker/WestCord).

**Key architectural call (already decided with the user):** 5 of Nabarun's 8
factors (commercial_fit, strategic_value, growth_revenue, brand_network,
feasibility — 71% of the total weight) are inherently qualitative judgments
that cannot be honestly computed by keyword/regex matching the way
`sector_alignment_score`/`company_size_score` work today. Faking them with
crude heuristics would just be arbitrary numbers dressed up as Nabarun's
formula. So:
- **`rule_engine.py` keeps its existing role** — a cheap, deterministic,
  LLM-free pre-filter that narrows vector search's ~20 candidates down to
  ~10 before the expensive LLM call. It gains one new cheap, genuinely
  computable dimension (`decision_authority`, from `designation` keywords)
  alongside its existing `sector`/`size` dimensions, and keeps `token_overlap`
  (CLAUDE.md explicitly requires "Token overlap: looking_for ↔ offers" as a
  rule-engine bullet) as the pre-filter's stand-in for commercial relevance
  until the LLM makes the real judgment. This produces a **pre-filter
  ranking score only** — it is no longer what gets stored as `Match.score`.
- **`llm_matcher.py` computes the real final score.** The LLM is asked to
  judge the 5 qualitative factors per candidate (0.0–1.0 each, with one-line
  definitions matching Nabarun's descriptions), and our own code combines
  them with the pre-filter's `sector`/`size`/`decision_authority` scores using
  Nabarun's exact fixed weights — never trusting the LLM to do the arithmetic
  itself. This final weighted score becomes `Match.score`.

**Explicitly out of scope for this change** (separate items from
`docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md`, not bundled in here): the ecosystem-role/
relationship-tag taxonomy (Item 2b), reverting to tier-differentiated match
quotas, a per-counterpart match cap, the 3-sentence reasoning format, and
cross-event/community matching (Item 3). This plan is scoped strictly to the
scoring formula.

## Decisions

- **New `app/services/matching/scoring_weights.py`** — single canonical
  source of truth for all 8 Nabarun weights as named constants (e.g.
  `COMMERCIAL_FIT_WEIGHT = 0.34`, `SECTOR_WEIGHT = 0.16`, ... summing to
  1.00), imported by both `rule_engine.py` (for its renormalized pre-filter
  subset) and `llm_matcher.py` (for the final weighted sum), so the two never
  drift out of sync.
- **New `app/services/matching/decision_authority.py`** (same one-concern-
  per-file pattern as `token_overlap.py`/`sector_size.py`):
  - `SENIOR_TITLE_KEYWORDS` (English + Dutch, since real sample data mixes
    both — "CEO", "founder", "owner", "director", "president", "partner",
    "chief", "vp", "directeur", "eigenaar", "oprichter", etc.) → 1.0
  - Mid-level keywords ("manager", "head of", "lead") → 0.5
  - Everything else / blank / unparseable → 0.0 (no data = no confidence,
    same convention as `sector_alignment_score`)
  - `classify_seniority(designation) -> float`
  - `decision_authority_score(a_designation, b_designation) -> float` =
    average of both sides' seniority (symmetric, matches `score_pair`'s
    existing symmetry contract)
- **`rule_engine.py` changes:**
  - Import `decision_authority_score` and the weight constants.
  - Renormalized pre-filter weights (documented in-file with the derivation):
    `TOKEN_OVERLAP_WEIGHT = 0.40`, `SECTOR_WEIGHT = 0.33`,
    `SIZE_WEIGHT = 0.15`, `DECISION_AUTHORITY_WEIGHT = 0.12` (sums to 1.00;
    sector:size:decision_authority preserve Nabarun's 16:7:6 ratio at 60%
    combined weight, token_overlap retained at 40% as the required, real-
    data-derived pre-filter signal).
  - `score_pair()` adds `decision_authority` to its returned dict and
    composite; same-company hard-exclusion logic unchanged.
  - Rename nothing in the public API — `composite_score` still exists and is
    still used for ranking/narrowing candidates within `rank_candidates`, but
    document clearly (docstring) that it is a pre-filter signal, not the
    stored match score.
- **`match_schema.py` changes:** `MatchItem` gains 5 new required fields —
  `commercial_fit`, `strategic_value`, `growth_revenue`, `brand_network`,
  `feasibility` (all `float`). Existing fields unchanged.
- **`llm_matcher.py` changes:**
  - `SYSTEM_PROMPT` updated to ask for the 5 new fields per match, each
    0.0–1.0, with one-line definitions adapted from Nabarun's README
    (commercial_fit = genuine business opportunity/complementary need;
    strategic_value = potential for a lasting partnership beyond one
    transaction; growth_revenue = growth/revenue upside from the
    relationship; brand_network = counterpart's brand/network reach value;
    feasibility = realistic likelihood the intro leads to an actual outcome).
  - `_validate_selection` extended to check each of the 5 new fields is in
    `[0.0, 1.0]` (same retry-once-on-ValueError path as existing checks).
  - `build_matching_prompt` includes `decision_authority_score` in the per-
    candidate pre-filter score line (alongside existing token_overlap/sector/
    size), so the LLM sees the full pre-filter picture.
  - `select_matches` computes, per selected match, a `score_breakdown` dict
    (all 8 named factors + the candidate's pre-filter sector/size/
    decision_authority values) and a `final_score` = the fixed weighted sum
    using `scoring_weights.py`'s constants — computed in Python, never
    trusted to LLM arithmetic. Both are added to each returned match dict.
- **`match_writer.store_match` changes:** new `score_breakdown: dict`
  parameter, persisted on both the genuine row and the mirrored
  `is_bidirectional=True` placeholder (a pair-level fact, same treatment as
  `reasoning`/`rank`/`score` today).
- **`Match` model + migration:** new `score_breakdown: Mapped[dict | None]`
  JSON column. New Alembic migration (next sequential revision).
- **`matching_tasks.match_participant` changes:** stop using the rule
  engine's `composite_score` as the stored score — use each match's
  `final_score`/`score_breakdown` from `select_matches`'s return instead when
  calling `store_match`.
- **`GET /events/{id}/matches` (events.py) changes:** `MatchOut` gains an
  optional `score_breakdown: dict | None` field so the 8-factor breakdown is
  visible via the API, consistent with how `score`/`reasoning` are already
  exposed.
- **`cost_estimator.py`:** small bump to
  `ESTIMATED_OUTPUT_TOKENS_PER_PARTICIPANT` to account for 5 extra floats per
  match in the LLM's JSON output (minor — not a structural change).
- **CLAUDE.md updates:** add `decision_authority`/designation-seniority as a
  new rule-engine bullet under "Step 4 — Rule Engine Filter", and add a row
  to "Confirmed Architecture Decisions" documenting the score-formula split
  (rule engine = cheap pre-filter with 4 dimensions; LLM = final 8-factor
  Nabarun-weighted score), so this isn't lost the way the original tier-quota
  table was silently overridden earlier in the project.

## Implementation

1. `app/services/matching/scoring_weights.py` — new, 8 named constants.
2. `app/services/matching/decision_authority.py` — new module as described.
3. `app/services/matching/rule_engine.py` — renormalized weights, new
   `decision_authority` dimension in `score_pair`.
4. `app/services/matching/match_schema.py` — 5 new `MatchItem` fields.
5. `app/services/matching/llm_matcher.py` — prompt update, validation
   update, `build_matching_prompt` shows decision_authority, `select_matches`
   computes `score_breakdown`/`final_score` via `scoring_weights.py`.
6. `app/services/matching/match_writer.py` — `score_breakdown` param, mirrored
   onto the placeholder reverse row.
7. `app/models/match.py` — `score_breakdown` JSON column.
8. New Alembic migration for the column.
9. `app/workers/matching_tasks.py` — use `final_score`/`score_breakdown`
   instead of rule-engine `composite_score` when calling `store_match`.
10. `app/routers/events.py` — `MatchOut.score_breakdown`.
11. `app/services/matching/cost_estimator.py` — small output-token bump.
12. `CLAUDE.md` — new rule-engine bullet + Confirmed Architecture Decisions
    row.
13. `docs/PLAN.md` — brief note, same pattern as prior out-of-task-list
    additions.

## Verification

1. Unit-level: `decision_authority_score` against real sample designations
   (e.g. "directeur/eigenaar" → 1.0, "Manager" → 0.5, blank → 0.0).
2. Re-run matching for the same event/participants used in the Nabarun
   comparison (Edwin Groenewoud/Temis Luxury, Britt Bleeker/WestCord) and
   confirm the new `score_breakdown` + `final_score` move those specific
   matches closer to Nabarun's approved picks than before — this is the
   concrete regression/improvement check, not just "it runs."
3. Confirm `_validate_selection` actually retries once and then raises
   `MatchSelectionError` if the LLM omits one of the 5 new fields or returns
   an out-of-range value (mirroring the existing test pattern for the other
   business-rule checks).
4. Confirm `GET /events/{id}/matches` returns `score_breakdown` for newly
   generated matches and `null`/absent gracefully for any pre-existing
   matches created before this change (no backfill planned — old rows simply
   won't have a breakdown).
5. Confirm the migration applies cleanly (`alembic upgrade head`) and
   `alembic current` shows a clean chain, same discipline as prior migrations
   this project.
