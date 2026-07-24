# Client Feedback Gap Analysis (`examples.docx`)

Source: `examples.docx`, uploaded by the client (updated 2026-07-23 with
additional feedback since the first pass). It now contains five pieces of
feedback: the original example prompt/response and two "idea" emails about
matching philosophy, plus two new additions — a follow-up ChatGPT exchange
about estimating company size/"corporate score" for sparse profiles, and a
full worked example of the client's own "SBIQ Matchmaking Methodology"
applied to real participants. This document checks each against what's
actually built today and estimates the effort to close the gap.

**Independent supporting evidence:** since the first version of this
document, we compared our actual match output (`our_response.json`, event 34)
against a client-approved reference run from Nabarun (`nabarun_response.json`,
event 3, `run_id: wave1-corporate-priority`, `"approved": true`) covering
overlapping participants. That comparison is referenced throughout below —
it's concrete, client-approved proof of the same gaps this document already
flagged, not just a hypothetical.

---

## 1. Priority matching criteria & example output

**What the client showed:** A sample ChatGPT prompt/response matching a
Sponsor (Ellen Spithoven, Preneurz — an AI-adoption/student-prototype program)
to three large corporates (WestCord Hotels, ABN AMRO, J.P. Morgan), each with
"why this match" bullets centered on strategic relevance and business
opportunity. The stated priority criteria: large corporates/enterprises,
sponsors/strategic partners, companies with active AI/innovation/
digitalization initiatives, and decision-makers/innovation managers/
transformation leaders/business developers.

**What's built today:**
- Sponsors are already processed first (`rule_engine.TIER_PROCESSING_ORDER`).
- The LLM matching step (`llm_matcher.py`) already produces exactly this
  output shape: 3 reasoning bullets + a personalized email draft + a LinkedIn
  draft per match, and is explicitly told "if none of the candidates are a
  good fit, return an empty matches list rather than forcing a bad match."
- The enriched profile already contains `designation` (job title),
  `company.summary`, and `company.recent_news` — the raw material for
  detecting "decision-maker" or "active AI initiative" signals already
  reaches the LLM in `_format_profile`.
- What's **not** there: nothing in the rule engine or the LLM prompt
  explicitly weights "large corporate/enterprise size," "active AI/innovation
  initiative," or "decision-maker title" as selection criteria. Today's
  scoring is token-overlap + sector-alignment + company-size-compatibility —
  none of which specifically reward "big company with an AI initiative and a
  senior title," even though the underlying data is present.

**New in this update — estimating company size when data is sparse.** The
docx now includes a follow-up ChatGPT exchange where the client asks it to
assess a participant ("Flowentry" — actually Flowently) whose company isn't
obviously a large corporate. ChatGPT reasons from public information to
produce a size bracket (micro/small SME/corporate) and explicitly recommends
prioritizing ABN AMRO/J.P. Morgan/WestCord over Flowently for Ellen
Spithoven's matches on that basis. It also names three concrete outputs the
client wants available per participant: **employee count estimate, revenue
category estimate, and a "corporate score."**
- **What's built today:** enrichment already tries to fill `employee_count`
  from Crunchbase (falling back to LinkedIn/company website per CLAUDE.md's
  source-mapping table), and `sector_size.py` already buckets company size
  from whatever number it finds. What's missing is exactly what the client is
  asking for here: there's no fallback *estimate* when no source returns a
  hard number (today it just stays blank), no revenue-category field at all,
  and no single "corporate score" — this would need to be a genuinely new
  synthesized field (likely LLM-inferred from the merged enrichment sources at
  normalization time, since it's explicitly meant to work from public/
  inferred information, not just structured data fields).
- **Effort: Low-Medium.** Extending `llm_normalizer`'s output schema with an
  estimated size bracket + revenue category + corporate score (all LLM-
  inferred, with a stated confidence/basis) is a schema + prompt change, not a
  new pipeline stage — closer to Item 1's original scope than to Item 2's.

**Verdict: mostly covered. Low effort to close the rest.**
This doesn't need a new subsystem — it's a prompt-tuning task. Add explicit
prioritization language to `llm_matcher.SYSTEM_PROMPT` (and optionally
surface `employee_count`/`designation` more prominently in `_format_profile`)
so the LLM is told to weight these signals when picking among rule-engine
candidates. No schema change, no new pipeline stage. Estimate: a few hours,
verified against a handful of real profiles. The corporate-score/estimated-
size addition above is a modest extension of the same low-effort bucket, not
a separate project.

**Confirmed by Nabarun's approved run:** its scoring weights include an
explicit `size` component (0.07) alongside `commercial fit` (0.34), and the
run's own README states "big corporates are not exempt (no over-allocation)"
— i.e. size matters but doesn't override quality. This matches the "mostly
covered, low effort" verdict here rather than suggesting size needs to be a
dominant factor.

---

## 2. "Ecosystem role" matching philosophy

**What the client argued:** Matching shouldn't default to industry/title/
similarity (e.g., don't match a luxury logistics provider with other logistics
companies). Instead, classify each participant by their *ecosystem role* —
examples given: Luxury Ecosystem Partner, Investment Ecosystem Builder,
Capital & Influence Network Multiplier, CEO Network Multiplier vs. Generic
Service Provider — and match on complementary business value, not similarity.
Also: enforce a minimum relevance bar ("no match is better than a bad match")
and return an explicit "no high-value matches identified" message rather than
force a weak one.

**What's built today:**
- `rule_engine.score_pair` is structurally a *similarity* engine: token
  overlap between `looking_for`/`offerings`, sector-alignment score, and
  company-size compatibility. There is no concept of "role" anywhere in the
  schema or scoring.
- There is no minimum-score gate. Whatever the rule engine ranks highest goes
  to the LLM, and while the LLM prompt already permits returning zero
  matches, there's no hard numeric threshold enforcing it — it's entirely
  left to LLM judgment call by call.

**Verdict: not built. Two separable pieces, different effort levels.**

- **Minimum relevance threshold — Low effort.** Add a `MIN_COMPOSITE_SCORE`
  cutoff before a candidate is even sent to the LLM (or key off the LLM's own
  confidence), and give `GET /events/{id}/matches` an explicit "no high-value
  matches identified" response shape for participants with zero results. This
  is a small, self-contained change.
- **Ecosystem role classification + role-complementary scoring — Medium-High
  effort.** This is a genuine philosophical change to the matching logic, not
  a tweak, and needs:
  - A new classification step (an LLM call, likely folded into existing
    normalization or added as a new post-enrichment step) that assigns each
    participant a role label from a defined taxonomy.
  - A new role-adjacency scoring table — the same pattern as
    `sector_size.SECTOR_ADJACENCY`, but for roles: which roles are valuable
    matches for which other roles.
  - A change to `score_pair`'s composite formula (new weight, or a
    re-weighting of the existing three) — today's formula rewards
    *similarity*, which is exactly what the client says is often the wrong
    signal.
  - A prompt update so the LLM matching step is told each pair's role
    relationship, not just raw profiles.
  - This also needs a **finalized role taxonomy from the client** — the docx
    gives 11 example role names and 4 worked examples, not an exhaustive
    list — plus real-data tuning so the change doesn't regress matches that
    already work well today. Added cost: one more LLM call per participant,
    partially offset by the existing `enriched_profiles` cross-event cache.

**Concrete evidence this is the right call — Nabarun's approved run vs. ours,
same people.** Edwin Groenewoud (Temis Luxury — the exact "luxury logistics"
example from this docx) was matched by our current system to Rim Alaoui
(Omoka, logistics-tech, score 0.05) and Geoffrey Burgh (B2B lead gen, score
0.036) — weak, similarity-based, and exactly the "another logistics company"
mistake the client describes. Nabarun's client-approved run matched the same
Edwin to Jupiter Capital Management and Ned Fund Finance (capital/investment
access, scores 0.86–0.88) — much closer to the docx's own prescription
("private banking professionals," "family offices"). Same pattern for Britt
Bleeker/WestCord: ours picked small local suppliers (lloff, Stomerij
Collectief, scores 0.08–0.34); Nabarun's picked ABN AMRO/Protect Eye/Ebicus
(scores 0.86–0.9) — literally the docx's own worked example. **This means the
taxonomy question below isn't purely open** — Nabarun's run already uses and
has client approval for a concrete 6-tag vocabulary: `corporate_entry_point`,
`potential_client`, `potential_supplier`, `strategic_partner`,
`innovation_partner`, `sector_affinity`. That's a smaller, already-validated
starting point, in contrast to inventing role labels from the docx's more
abstract 11-item list from scratch.

---

## 3. Cross-event / community / historical matching hierarchy

**What the client proposed:** When no strong match exists in the current
event, don't stop — search, in order: Community Network (e.g. "MeerBusiness
Amsterdam," "Businessclub Over-Amstel") → Previous Events → Cross-Community
Network. Tag every match with its source (Current Event / Community Network /
Previous Event / Cross-Community Network). Stated long-term vision: "Event
Matching → Network Intelligence → Ecosystem Intelligence."

**What's built today:**
- Vector similarity search (`similarity_search.py`) is **always filtered by
  `event_id`** — this is a confirmed, documented architecture decision
  ("never cross-event"). This directly conflicts with what's being asked
  here.
- `Participant` rows are entirely event-scoped — every event upload creates
  fresh rows. The only durable, cross-event concept in the system is
  `enriched_profiles` (an email-keyed enrichment cache added purely for
  cost/speed reasons) — it has no matching role and no notion of community.
- `Match` has no `source` field. There is no `communities` table or any
  participant-to-community membership anywhere in the schema.

**Verdict: not built at all. High effort, and it reverses a confirmed
architecture decision.**
This is the largest ask of the three. It requires:
1. A durable person/contact identity that persists across events (today's
   `Participant` rows are disposable per event; `enriched_profiles` is the
   closest existing anchor but isn't wired into matching at all).
2. A new `communities` concept and participant-to-community membership.
3. A cross-event similarity search path that deliberately does **not** filter
   by `event_id` — built as a new function alongside the existing one, not a
   modification of it, so the current event-scoped guarantee stays intact.
4. Priority-hierarchy orchestration in the matching pipeline: try
   current-event, then community, then historical, then cross-community,
   stopping at the first tier with a strong-enough match.
5. A `match_source` field on `Match`, plus API/UI support for surfacing it.

This is a new architectural layer, not an extension of the existing pipeline.
It's also the one item where the client is describing a strategic direction
more than a concrete spec — before any build starts, we'd need answers to:
what defines a "community" and how participants get assigned to one, how much
match history to search, and what score counts as "strong enough" to stop
searching and not fall through to the next tier.

---

## 4. Client's own "SBIQ Matchmaking Methodology" experiment (new)

**What the client showed:** the client fed both prior documents into their own
GPT chat and asked it to apply "the SBIQ Matchmaking Methodology" (a document
we don't have a copy of — it's referenced, not attached) to the real
participant list, with a specific reasoning format: 3 sentences per bullet
point, "why SBIQ selected this match." The stated first-layer logic:
- Prioritize Sponsors → Premium Members (PM) → Business Members (BM)
- Focus on commercial relevance rather than industry similarity
- Prioritize revenue opportunities, strategic partnerships, innovation
  potential, corporate access and ecosystem expansion
- Create a limited number of high-quality matches rather than maximizing the
  number of introductions
- Focus on business outcomes rather than networking activity alone

**What's built today:** this is almost entirely a restatement of Items 1 and
2 above, plus one confirmation and one new emphasis:
- The **Sponsor → PM → BM processing order** is now stated for a third time
  across three independent sources (CLAUDE.md's original priority table,
  Nabarun's approved run, and this client experiment) — all three agree, and
  all three disagree with our current flat, non-differentiated match quota.
  This should be treated as settled, not still open.
- **"Limited high-quality matches over maximizing introductions"** reinforces
  Item 2a's minimum-relevance-threshold ask — nothing new to build beyond
  what's already scoped there.
- The **3-sentence, "why SBIQ selected this match" reasoning format** is a
  concrete, checkable prompt-output spec we don't currently enforce —
  `llm_matcher.SYSTEM_PROMPT` asks for "exactly 3 short bullet strings" but
  doesn't require each bullet to be a full 3-sentence explanation; today's
  bullets are single short sentences. This is a prompt-wording change only.

**A real inconsistency worth flagging, not silently resolving:** in the
*first* example (Item 1), Ellen Spithoven (Preneurz, Sponsor) is matched to
three large corporates (WestCord, ABN AMRO, J.P. Morgan) specifically because
the client's stated priority is large-corporate size. In *this* new
methodology experiment, the same Ellen Spithoven is instead matched to
Kristian Heck (Kristian AI), Evert Lassche (LMI Noord-Holland), and Bas
Ambachtsheer (Bitsing) — three much smaller BM-tier companies, reasoned on
"shared AI focus" and "leadership meets innovation" rather than company size
at all. Both came from the client's own experimentation, and they point in
different directions for the same recipient. This should go back to the
client as a direct question rather than us picking one interpretation to
build toward.

**Verdict: no new build item.** This section is corroborating evidence for
Items 1 and 2, not a fourth thing to implement — folded into those effort
estimates and the open questions below.

---

## Recommended framing & sequencing

None of these map cleanly onto CLAUDE.md's existing Phase 1/2/3 boundaries —
they're new product direction, not backlog items for phases already defined.
Recommend tracking them as a new "Phase 4+ / Post-MVP backlog" rather than
shoehorning them into the current phase table.

Suggested order (updated — Nabarun's approved run now gives us a validated
reference to build against instead of reverse-engineering from docx examples
alone):
1. **Ask Nabarun for the actual scoring logic/script** behind
   `nabarun_response.json`, not just the output — the README gives weights
   and a relationship taxonomy, but not the underlying rationale-generation
   logic. Cheap, and de-risks everything below it.
2. **Item 1** (low effort) — prompt tuning + the new corporate-score/size-
   estimate addition, can be done anytime, no dependencies.
3. **Item 2a**, the minimum relevance threshold (low effort) — small,
   self-contained, confirmed independently by both the docx ("no match is
   better than a bad match") and this methodology experiment ("limited
   high-quality matches over maximizing introductions").
4. **Revert the tier quota** from flat to Sponsor 3 / Premium 2 / Business 1
   — now confirmed by three independent sources (CLAUDE.md's original table,
   Nabarun's approved run, this methodology experiment). Low effort, no
   longer worth treating as deferred.
5. **Item 2b**, ecosystem role classification (medium-high effort) — start
   from Nabarun's already-approved 6-tag vocabulary
   (`corporate_entry_point`/`potential_client`/`potential_supplier`/
   `strategic_partner`/`innovation_partner`/`sector_affinity`) rather than
   inventing new labels from the docx's more abstract list; still needs
   real-data tuning before trusting it in production.
6. **Item 3** (high effort) — needs client clarification on community
   definitions, historical search scope, and match-quality cutoffs before any
   implementation begins; also needs an explicit decision to reverse the
   "never cross-event" design choice.

## Open questions for the client

- **New:** Ellen Spithoven was matched to three large corporates in one
  example and three small/mid BM-tier companies in another (Section 4) — both
  from the client's own experiments. Which reflects the actual intent: size-
  first prioritization, or commercial-relevance-first regardless of size?
- **New:** should "corporate score"/employee-count estimate/revenue-category
  be stored fields on the participant profile (so they're computed once and
  reused), or acceptable as an on-the-fly LLM judgment at matching time only?
- Can we get the actual "SBIQ Matchmaking Methodology" document referenced in
  Section 4, rather than only its GPT-applied output? It's clearly the
  authoritative source the client is already using to evaluate match quality.
- Can we get Nabarun's actual scoring implementation (script/prompts), not
  just `nabarun_response.json`'s output and README? It would save us from
  reverse-engineering an approved methodology from examples alone.
- What is the complete, final list of ecosystem roles (not just the 11
  examples given, or Nabarun's 6 tags), and are they mutually exclusive per
  participant or can someone hold more than one?
- What is the authoritative list of "communities," and how does a participant
  get associated with one (self-reported at signup? organizer-assigned? an
  existing membership system)?
- What numeric or qualitative bar defines "strong enough" to stop the
  fallback search at a given tier, versus falling through to the next one?
- Is reversing the "vector search never crosses event boundaries" decision
  acceptable given its data-scoping implications (a participant's profile
  from one event becoming visible as a candidate in a different event/
  organizer's matching run)?
