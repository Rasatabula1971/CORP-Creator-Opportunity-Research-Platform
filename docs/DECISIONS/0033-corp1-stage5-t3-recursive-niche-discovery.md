# ADR-0033 — CORP1 Stage 5, T3: Recursive Niche Discovery Engine

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 3 ("Discover Broad
Topics and Drill Into Niches", "Niche Exclusion Rules", "Research
Registry"), Stage 4, and Stage 5, task T3 (flagged as the highest-risk
task in the build order — recursion + cost control, human gate includes
ARCHITECTURE REVIEW REQUIRED)

## Context

T3 replaces the single-level "discover -> drill-down" description from
the CORP1 spec's Phase 1.3/1.4 with the frozen recursive behavior: a
broad topic fans out across every capability provider (T1, wired by T2)
in parallel, an LLM synthesizes named niches from the evidence, and any
niche not yet specific enough for a concrete product recurses into itself
as the next query — one level deeper, up to a depth-3 hard cap.

The frozen acceptance criteria left several mechanisms underspecified at
the level actual code has to work at. This ADR documents every
interpretive decision made to fill those gaps, since T3's own human gate
explicitly allows ARCHITECTURE REVIEW REQUIRED if any of them don't hold up.

## Decisions

### 1. Exclusion uses `NicheCandidateStatus.REJECTED`, not `policy_class`

T0's ADR-0030 corrected the frozen spec to reuse `Niche.policy_class =
excluded` instead of adding a new field — but T3 operates on
`NicheCandidate`, which has no `policy_class` at all; only the later-stage
`Niche` does. Setting `policy_class` from T3 is impossible by construction.

**Resolution:** a candidate matching an exclusion category is created with
`status = NicheCandidateStatus.REJECTED` and `extra = {"excluded_category":
...}` — reusing the status value whose own comment already says exactly
this: `# broad domain, policy, or human decision`. Every downstream stage
(canonicalization, qualification) only ever queries `status ==
NicheCandidateStatus.STAGED`, so a REJECTED candidate provably never
reaches creator discovery, matching the acceptance criterion's intent
without inventing a new mechanism. `policy_class` remains reserved for
when/if a candidate is later promoted to a canonical `Niche` — which an
excluded candidate never is.

Exclusion is checked twice: once on the raw keyword **before** spending
evidence-collection budget (cheap, fails fast), and again on every
synthesized candidate's name + description **after** synthesis, since
evidence can reveal a category the bare keyword didn't (e.g. "hobbies" is
fine, but a niche the evidence surfaces under it, "Sports Betting Odds",
is not).

### 2. Only `AdapterFamily.NICHE` adapters fan out for topic queries

T2 wired `ProblemProvider`/`DissatisfactionProvider` onto `YouTubeAdapter`
and `RedditAdapter`, both `AdapterFamily.CREATOR_BOUND`. Their `collect()`
expects a channel handle or subreddit name — calling
`fetch_problems("home espresso")` on `YouTubeAdapter` would try to resolve
"home espresso" as a YouTube channel and fail outright. T3's fan-out
therefore only builds the 8 `AdapterFamily.NICHE` adapters (the same
`NICHE_PLATFORMS` set `MultiSourceDiscovery` already uses, for the same
reason), never YouTube or Reddit. This was found by reading what
`collect()` on each actually accepts, not assumed from the capability
mapping table alone.

### 3. Registry check: exact match against `Niche`/`NicheAlias`

"Checks each candidate against `Niche.next_recheck_at`" is implemented as
a case-insensitive lookup of the keyword against `Niche.canonical_name` OR
`NicheAlias.alias` (reusing the existing functional index built for
exactly this kind of match, per docs/DECISIONS/0002) before spending any
evidence-collection budget on it. A match with `next_recheck_at` still in
the future is skipped entirely — no adapter calls, no LLM call. A keyword
with no matching Niche (the common case pre-canonicalization) is always
treated as due.

**Fixed per Stage 8 review:** the lookup uses `func.lower(column) ==
keyword.lower()`, not `column.ilike(keyword)`. The original `ilike(keyword)`
passed the raw keyword unescaped, so a literal `%` or `_` in a topic string
would be interpreted as a SQL wildcard — e.g. `"Home%Espresso"` as a LIKE
pattern matches the differently-spelled `"Home Espresso"` (the `%` matches
the space), a false-positive registry hit that would wrongly skip real
work. Exact comparison has no such ambiguity. Covered by
`test_registry_check_does_not_treat_keyword_as_sql_wildcard_pattern`.

**Known gap, not fixed here (out of T3's frozen file scope):**
`corp/workers/intelligence/niche_verification.py` sets
`Niche.last_researched_at` on a scan but never computes
`next_recheck_at`. Nothing in the codebase currently sets it. This means
the registry check above is correctly implemented but presently inert in
production — it will never actually skip anything until whatever task
touches niche verification next also sets `next_recheck_at =
last_researched_at + 90 days`. Flagging this explicitly so it isn't
mistaken for something T3 was supposed to fix.

### 4. Multi-capability duplicate evidence: intentional two-lens persistence

ADR-0032 (T2) flagged this as unresolved: Reddit/AppStore/Marketplace's
two capabilities delegate to the same `collect()`, so the same raw item
reached through both would either be double-stored or one lens would be
lost. **Resolved as intentional two-lens evidence**: the same raw item is
persisted **once per distinct `evidence_type`** it legitimately
represents (a marketplace listing IS both a transaction signal and a
solution signal) — a `(evidence_type, source_platform, source_id)` triple
is the dedup key, not just `(source_platform, source_id)`. Verified
directly: `test_two_capability_adapter_persists_once_per_evidence_type`
confirms one fake listing queried through two capabilities becomes exactly
two `Evidence` rows (`SOLUTION` and `DISSATISFACTION`), never four, never
one.

### 5. Evidence pool includes pre-existing rows, not just newly-inserted ones

Found while writing tests, not anticipated in design: a naive
"return only rows I just inserted" made deeper recursion levels see
**empty** evidence whenever an adapter's query at depth N+1 happened to
resurface an item already persisted at depth N (the global dedup by
design prevents re-inserting it) — silently starving the LLM synthesis
call and stopping recursion with no error. Fixed: `_collect_evidence`
still only *writes* a row once (dedup preserved), but always *returns* the
full set relevant to the current keyword, fetching the existing row when
one is found rather than dropping it. `test_depth_hard_cap_stops_recursion`
exercises exactly this path (every level's fake adapter legitimately
"resurfaces" the same fixture item) and would have failed against the
naive version.

### 6. LLM provider is required, not optional

Unlike `NicheCandidateGenerator` (embedding-clustering with LLM naming as
an enhancement — a deterministic keyword label always exists as
fallback), T3's entire premise (Option B) is LLM synthesis across
multi-source evidence. There is no deterministic equivalent for
"identify several niches from a raw evidence pool." `RecursiveNicheDiscovery`
requires a real `LLMProvider`; there is no `provider=None` degraded path.

### 7. Ungrounded synthesized niches are dropped, never given a fallback name

Mirrors `niche_naming.check_grounding`'s existing convention exactly (the
same function is reused, not reimplemented): every niche the LLM proposes
must cite `evidence_terms` that verifiably appear in the evidence shown.
An ungrounded niche is logged and dropped — no candidate is created for
it. Enforces "niches come from evidence, not imagination" (Stage 3) at the
one point it could otherwise be violated.

## Known risk: no aggregate cost ceiling across one `discover()` call

Flagged by Stage 8 review, not resolved here. The frozen per-level caps
(breadth 15 at depth 0, 10 per branch at depth 1–2, depth capped at 3) are
enforced correctly and cannot be exceeded — verified directly. But they
compound *multiplicatively* across one `discover()` call: in the
pathological case where the LLM rarely marks a niche `specific_enough`,
one broad topic could drive roughly 15 × 10 × 10 × 10 ≈ 1,600 `_drill`
calls, each fanning out across up to 8 adapters × their capabilities —
tens of thousands of adapter calls and well over a thousand LLM calls from
a single `discover(campaign_id, topic)` invocation. This is inherent to
the frozen spec's own per-level numbers (Stage 5's T3 card specifies only
per-level caps, not a total), not something T3 introduced, but it is
exactly the kind of cost-control question this task's human gate exists
to catch. An aggregate ceiling (e.g. a total `_drill` call budget per
`discover()` invocation, independent of depth/breadth) is a candidate fix
for a future revision if real usage shows this matters in practice.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/intelligence/niche_discovery.py` | New — `RecursiveNicheDiscovery`, `synthesize_niches`, `matched_exclusion`, `DiscoveryConfig`. |
| `rules/niche_discovery_prompt.yaml` | New — recursion caps (depth 3, breadth 15/10/10, 90-day recheck), the four Stage 3 exclusion categories as deterministic keyword lists, synthesis prompt version. |
| `tests/integration/test_niche_discovery.py` | New — 13 tests: depth/breadth caps, keyword- and candidate-level exclusion, registry freshness (both directions, plus the wildcard-escaping fix), grounding, the two-lens duplicate-evidence behavior, campaign-not-found. |

No changes to `corp/api/jobs.py` (T4's job) or any other existing file.

## Verification

- `mypy --strict` clean; `ruff check` clean.
- 13 new tests pass.
- Full `tests/integration/` (229 passed, 1 pre-existing unrelated skip —
  gated on `CORP_LIVE_TESTS=1`, not something T3 touches) and
  `tests/workers/` (553 tests) suites pass with zero regressions. (An
  earlier verification pass on this ADR wrongly reported 274 for
  `tests/integration/` alone — that number came from a combined run that
  also included three unrelated `tests/workers/` files; corrected here
  per Stage 8 review.)

## Consequences

- T4 (campaign pipeline rewire) can call `RecursiveNicheDiscovery.discover(
  campaign_id, topic)` as the new `discover` stage in place of the old
  single-level flow.
- Whoever next touches `niche_verification.py` should also close the
  `next_recheck_at` gap noted in decision 3 — until then, the research
  registry never actually skips a re-scan.
- The exclusion keyword lists in `rules/niche_discovery_prompt.yaml` are a
  starting set, not exhaustive — expected to be extended as real usage
  surfaces gaps, the same way the frozen mapping tables have been
  corrected twice already (T0, T2).
