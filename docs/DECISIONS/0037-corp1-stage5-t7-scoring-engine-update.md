# ADR-0037 — CORP1 Stage 5, T7: Scoring Engine Update

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Phase 1.7 ("Update Scoring
Engine") and Stage 5, task T7

## Context

T7's frozen scope is narrow by design: `corp/core/scoring/engine.py` and
`rules/scoring.yaml` only — no `scoring_pipeline.py`, no migration. The
CORP1 spec's own Phase 3.6 ("Full Scoring Integration") is explicitly a
later, separate task that wires evidence-by-capability-type into the live
pipeline "once all evidence providers are in place." T7 is the first
pass: add the four new dimensions Phase 1.7 calls for as pure functions,
proven with fixture-driven unit tests, without touching the pipeline that
will eventually call them.

## Decisions

### `engine.py` stays a pure scoring-math library — no DB, no pipeline call

Every existing function in this module takes already-extracted numbers
(a count, a score, a list) and returns a 0–1 float; none of them query
the database. The four new functions follow the same shape exactly —
`score_external_demand_strength(trend_evidence_count, search_intent_
evidence_count)`, not a function that queries `Evidence` itself. Actually
counting `Evidence` rows by `evidence_type` (T0) and calling these
functions with real numbers is `scoring_pipeline.py`'s job, deliberately
deferred to Phase 3.6 (T21 in the build order, per the spec's own
build-order table) — reusing exactly the scope boundary the CORP1 spec
itself already drew.

### Four new functions, matched to Stage 4's capability-type mapping

| Function | Capability(ies) | Higher score means |
| --- | --- | --- |
| `score_external_demand_strength` | TrendProvider + SearchIntentProvider | more external demand signal |
| `score_solution_saturation` | SolutionProvider | less existing competition (whitespace) |
| `score_purchase_intent` | TransactionProvider | more evidence people already pay |
| `score_audience_dissatisfaction` | DissatisfactionProvider | more evidence current solutions fail people |

`score_solution_saturation` is named distinctly from the two existing
saturation functions (`score_competition_saturation`: the creator's own
storefront; `score_competitor_saturation`: a manually tracked
`Competitor` list) — same "higher is better, neutral 0.5 with no
research yet" convention, but reading a third, independent evidence
source (T1/T2's `SolutionProvider` adapters: marketplace listings, app
store apps, Product Hunt launches, published books). All three run side
by side and are blended into the same aggregate; naming them distinctly
prevents confusing three different evidence sources answering the same
question.

### Weight rebalancing: uniform proportional scale-down, not ad hoc numbers

The ten existing weights (`rules/scoring.yaml`) were each multiplied by
0.76, preserving their exact relative proportions, freeing up 0.24 for
the four new dimensions (`external_demand_strength` 0.06,
`solution_saturation` 0.04, `purchase_intent` 0.08 — weighted higher,
matching the spec's own framing of transaction evidence as "the most
powerful demand signal available" — `audience_dissatisfaction` 0.06).
`test_scoring_yaml_weights_sum_to_one` checks the real file, not a
fixture copy, directly — a future rebalancing mistake is caught here,
not only by manual review.

### Confirmed backward-compatible with the unmodified live pipeline

`scoring_pipeline.py` calls `compute_score(components, self._weights)`,
and `compute_score`'s total-weight normalization is keyed off
`component_scores`' own keys (`for k in component_scores`), not the full
weights dict — a `component_scores` dict that only supplies the original
ten dimensions (today's actual behavior, since the four new ones aren't
wired into any pipeline yet) still normalizes correctly against the new
14-key weights file, dividing by the weight actually present rather than
the full 1.0. `test_new_dimensions_compute_score_with_existing_
components` proves this directly against the real rules file, not an
assumption.

## Files changed

| File | Change |
| --- | --- |
| `corp/core/scoring/engine.py` | Added `score_external_demand_strength`, `score_solution_saturation`, `score_purchase_intent`, `score_audience_dissatisfaction`. |
| `rules/scoring.yaml` | Version bumped `2.1.0` → `2.2.0`; four new weight keys; the original ten rescaled by 0.76, still summing to exactly 1.0 (verified programmatically, not just by hand). |
| `tests/workers/test_scoring_engine.py` | Added 22 tests: one dimension coverage per new function (zero/positive/cap/monotonicity cases), the real-file weight-sum check, an exact-per-weight-value check (added post-Stage-8-review), and two `compute_score` compatibility tests (partial ten-dimension input, and full fourteen-dimension input). |

No changes to `scoring_pipeline.py`, any adapter, or any model — matching
T7's frozen scope exactly.

## Verification

- `mypy --strict` is clean on `corp/core/scoring/engine.py`. It is **not**
  clean on `tests/workers/test_scoring_engine.py` — same pre-existing,
  repo-wide `no-untyped-def` gap (test functions lacking `-> None`) as
  every other test file in this project; T7 did not introduce it and
  every other test file, including ones this task never touched, fails
  the same way.
- `ruff check` clean on both changed `.py` files.
- `python -c` weight-sum check: exactly `1.0` across all 14 keys.
- 21 new tests pass (54 total in the file, 33 pre-existing + 21 new),
  including `test_scoring_yaml_weights_exact_values`, which asserts each
  of the 14 weights against its exact expected value (not just their
  sum), added after Stage 8 review flagged that the sum-only check would
  let a silent reweighting slip through.
- Full `tests/workers/` (574 tests, up from 553) and `tests/integration/`
  + `tests/api/` (314 passed, 1 pre-existing unrelated skip, unchanged
  from T6's baseline — confirming no test hardcodes an exact aggregate
  score that the rebalancing would have shifted) suites pass — zero
  regressions.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF, none of which T7 touched — pre-existing dev-
environment changes from earlier in this session, unrelated to scoring.
Not staged as part of this task's commit.

## Consequences

- Phase 2/3 adapter tasks (T11–T21) have concrete scoring functions ready
  to receive their evidence counts once built — Phase 3.6 ("Full Scoring
  Integration") becomes a wiring task against already-tested math, not a
  from-scratch design task.
- Any future engine.py change must keep `rules/scoring.yaml`'s weights
  summing to 1.0; `test_scoring_yaml_weights_sum_to_one` will catch a
  regression here automatically.
