# Matching Engine — Metrics Covered (Current State)

This documents every scoring metric currently implemented in the matching
pipeline, where each one sits in the pipeline, and how they map back to the
client's stated priorities. Reflects the codebase as of the ecosystem-role/
decision-authority addition on branch `feature/rule-engine-scoring-rewrite`.

## Where these metrics sit in the pipeline

```
Step 3: Vector similarity search (embedding cosine-distance, top 20)
   |
Step 4: Rule engine - THE 5 METRICS BELOW - narrows top 20 -> top 10
   |
Step 5: LLM reasoning - selects final 3-5 matches, writes drafts
```

All 5 metrics below live in **Step 4 only**. `Match.score` (the value
ultimately stored and shown via `GET /events/{id}/matches`) is this same
rule-engine composite - the LLM step does not currently re-score or override
it.

## The 5 metrics

| Metric | Weight | Range | Source module |
|---|---|---|---|
| Role adjacency | **0.40** | `{0.0, 1.0}` (binary) | `ecosystem_role.py` |
| Token overlap | 0.25 | `[0.0, 1.0]` | `token_overlap.py` |
| Sector alignment | 0.15 | `{0.0, 0.5, 1.0}` | `sector_size.py` |
| Company size compatibility | 0.10 | `{0.0, 0.5, 1.0}` | `sector_size.py` |
| Decision authority | 0.10 | `[0.0, 1.0]` (avg of two `{0, 0.5, 1.0}` values) | `decision_authority.py` |

Weights sum to 1.00. `role_adjacency` is deliberately the dominant factor -
see "Why role adjacency is weighted highest" below.

### Role adjacency (0.40)

Classifies each participant into one **ecosystem role** (done once per
participant, folded into the existing enrichment normalization LLM call -
no added API call) and scores `1.0` if two participants' roles are
*complementary*, else `0.0`. Deliberately does **not** reward identical
roles - two participants competing for the same counterparts isn't a
complementary match.

**Taxonomy** (11 categories, taken verbatim from the client's `examples.docx`):
Direct Buyer, Direct Seller, Network Multiplier, Ecosystem Builder, Investor,
Deal Flow Source, Strategic Connector, Market Access Partner, Community
Leader, Specialist Advisor, Corporate Entry Point.

**Adjacency table** (hand-authored, first proposal - flagged as the most
subjective part of the system, tune based on real outcomes):

| Role | Complementary to |
|---|---|
| Direct Buyer | Direct Seller, Market Access Partner, Corporate Entry Point |
| Direct Seller | Direct Buyer, Investor, Deal Flow Source, Corporate Entry Point, Market Access Partner |
| Investor | Direct Seller, Deal Flow Source, Strategic Connector, Corporate Entry Point |
| Deal Flow Source | Investor, Direct Seller, Network Multiplier |
| Network Multiplier | Deal Flow Source, Community Leader, Strategic Connector, Ecosystem Builder |
| Ecosystem Builder | Network Multiplier, Community Leader, Strategic Connector, Market Access Partner |
| Strategic Connector | Investor, Network Multiplier, Ecosystem Builder, Corporate Entry Point |
| Market Access Partner | Direct Buyer, Direct Seller, Ecosystem Builder, Corporate Entry Point |
| Community Leader | Network Multiplier, Ecosystem Builder, Specialist Advisor |
| Specialist Advisor | Direct Buyer, Direct Seller, Corporate Entry Point, Community Leader |
| Corporate Entry Point | Direct Buyer, Direct Seller, Investor, Strategic Connector, Market Access Partner, Specialist Advisor |

### Token overlap (0.25)

Szymkiewicz-Simpson overlap coefficient between one participant's
`looking_for` and the other's `offerings` (both directions, averaged).
Chosen over Jaccard since the two fields are often very different lengths.
English-only tokenizer with stopword removal.

### Sector alignment (0.15)

Keyword-classifies each participant's free-text `sector` into one of ~18
categories. `1.0` if categories match exactly, `0.5` if categories are
adjacent (hand-authored adjacency table), `0.0` otherwise or if
unclassifiable.

### Company size compatibility (0.10)

Parses free-text `company_size` into an employee-count estimate, buckets
into 5 size ranges. `1.0` same bucket, `0.5` one bucket apart, `0.0` two or
more apart or unparseable.

### Decision authority (0.10)

Keyword-classifies `designation` (English + Dutch titles) into senior
(`1.0` - CEO/Founder/Director/directeur/eigenaar/etc.), mid-level (`0.5` -
Manager/Head of/Lead), or unclassifiable (`0.0`). Pair score is the average
of both sides - rewards pairs where both participants hold real
decision-making authority.

## Why role adjacency is weighted highest

The original 3-metric formula (token overlap 0.5, sector 0.3, size 0.2) was
empirically shown to score **near-zero** for a client-approved reference
run's real matches - e.g. Britt Bleeker (WestCord, hotels) matched to Derek
Lampe (ABN AMRO, banking) scored 0.03 composite, because none of those 3
metrics can see any connection between a hotel group and a bank. All three
are fundamentally *similarity* signals; that pairing is valuable *because*
it's complementary, not similar. Role adjacency is the metric that actually
captures this - after adding it, the same pair scored 0.43. See
`docs/CLIENT_FEEDBACK_GAP_ANALYSIS.md` (Item 2) and
`docs/PREFILTER_COST_ANALYSIS.md` for the full investigation.

## Alignment with the client's stated priorities

| Metric | Client's ask (`examples.docx`) | Alignment |
|---|---|---|
| Role adjacency | Item 2: classify by ecosystem role, match on complementary value not industry similarity | Direct implementation |
| Decision authority | Item 1: prioritize "decision-makers, innovation managers, transformation leaders" | Direct implementation |
| Company size | Item 1: prioritize "large corporates and enterprise organizations" | Partial - bucket-compatibility only, no "corporate score"/revenue-category estimate yet |
| Token overlap / sector | Not explicitly requested - original system design | Retained but de-weighted, since the client's own thesis is that pure similarity is often the wrong signal |

## What's verified, and what's still a known gap

**Verified** (live, against real data - see `docs/PLAN.md`'s Phase 5 addendum):
real LLM role classification tested against 7 real participants from a
client-approved reference run; 3 of 5 real matches showed dramatic composite
score improvement (0.03-0.12 -> 0.43-0.50) once correctly classified.

**Known gap, not yet addressed:** none of the 5 metrics above matter if a
candidate never reaches Step 4 in the first place. The **Step 3 vector-
similarity pre-filter** (top 20 by embedding distance) still runs first and
was confirmed to exclude all 5 of the real test matches before the rule
engine ever scores them - similarity search has the same "can't see
complementary-but-dissimilar pairs" blind spot as the old rule engine did.
Widening or replacing that gate is the next piece of work, not yet built.
