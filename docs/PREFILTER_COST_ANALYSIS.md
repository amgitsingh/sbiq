# Cost of Removing the Similarity Pre-Filter

## Context

While reverse-engineering Nabarun's client-approved matching run (see
`CLIENT_FEEDBACK_GAP_ANALYSIS.md`, Item 2), we found that Nabarun's *actual*
matches for two real participants — Edwin Groenewoud (Temis Luxury) and Britt
Bleeker (WestCord) — fall well outside both of our current pre-filter stages:

- **Vector similarity search** (top 20 of 74 candidates): Nabarun's real
  matches ranked 21st–57th by cosine similarity — none would survive.
- **Rule engine** (deterministic `token_overlap`/`sector`/`size`/
  `decision_authority` scoring): all 5 real matches scored 0.03–0.12
  composite, with `token_overlap`, `sector`, and `size` flat `0.0` in every
  case. Only `decision_authority` (12% of the pre-filter weight) was
  nonzero.

This raised the obvious question: what if we just remove the pre-filter and
let the LLM see every participant as a candidate, matching Nabarun's own
stated approach ("whole attendee list is eligible as a counterpart")? This
document quantifies that cost.

## Real measurement: event 34

Average enriched-profile size, measured directly from real data (75
enriched participants, event 34): **~136 tokens** (545 chars ÷ 4 chars/token).

Pricing used: `gpt-4o` (the currently configured `AI_MODEL`) —
$0.0025/1K input tokens, $0.01/1K output tokens.

## Cost comparison — event 34 (75 participants, ~26 matching-eligible)

| | Current (10 candidates/prompt) | Full pool, no pre-filter (74 candidates/prompt) |
|---|---|---|
| Input tokens/LLM call | 136 × 11 ≈ 1,496 | 136 × 75 ≈ 10,200 |
| Input cost/participant | $0.0037 | $0.0255 |
| Output cost/participant | $0.006 (flat — output size doesn't scale with candidate count) | $0.006 |
| **Total/participant** | **$0.0097** | **$0.0315** |
| **Event total** (~26 eligible) | **~$0.25** | **~$0.82** |

For this specific event size, ~3.3x — noticeable but not alarming on its own.

## Why it doesn't stay that mild: O(N) vs O(N²)

Today's per-participant cost is **independent of event size** — the rule
engine always caps the LLM's candidate list at a fixed count (10), so total
event cost scales linearly with the number of eligible participants (O(N)).

Removing the pre-filter makes candidates-per-prompt equal to the whole
participant list, so per-participant cost now scales with N too — making
**total event cost O(N²)**:

| Event size | Current total cost | Full-pool total cost | Multiplier |
|---|---|---|---|
| 75 (event 34) | ~$0.25 | ~$0.82 | 3.3x |
| 300 | ~$1.95 | ~$21.60 | 11x |
| 1000 | ~$6.82 | ~$242 | 35x |

At ~1000 participants, the full-pool prompt (~136K input tokens) would
likely **exceed the model's context window entirely** (gpt-4o-class models
cap around ~128K tokens) — past a certain event size this isn't just
expensive, it's technically infeasible without restructuring the call
(batching, summarized profiles, etc.).

## Conclusion

CLAUDE.md's own design principle is explicit about why the pre-filter
exists: *"The LLM only sees a tiny pre-filtered set — cost stays low even
for 300+ participant events."* Removing the pre-filter outright defeats that
goal at scale — it isn't a free way to fix the exclusion problem.

**The actual problem is that our current pre-filter is similarity-based**
(embedding cosine-distance + keyword-matched sector/token-overlap), and
similarity is structurally the wrong signal for the complementary-but-
dissimilar matches the client wants (Edwin/luxury-logistics ↔ Jupiter
Capital/investment access). The fix isn't removing the filter — it's
replacing the *kind* of filter:

- **Role classification** (one LLM call per participant, foldable into the
  existing `llm_normalizer.py` enrichment call for near-zero added cost) —
  O(N), same cost class as today's enrichment step.
- **Role-adjacency scoring** (a deterministic lookup table, same pattern as
  today's `SECTOR_ADJACENCY`) — O(1) per pair, no LLM call, no cost impact.
- The LLM matching step still only sees a narrowed top-10 candidate
  shortlist, same as today — matching-run LLM cost stays at ~$0.25 for
  event 34, not $0.82–$242.

This is `CLIENT_FEEDBACK_GAP_ANALYSIS.md`'s Item 2b (ecosystem role
classification), and it's the next piece of work — see that document for
the taxonomy options (Nabarun's 6-tag vocabulary vs. the client's more
abstract role list) before implementation begins.
