# ADR-0044 — CORP1 Stage 5, T21: Full Scoring Integration (Phase 3.6)

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Phase 3.6 "Full Scoring
Integration" and Stage 5, T21

## Context

T7 (ADR-0037) added four pure scoring functions to `corp/core/scoring/engine.py`
— `score_external_demand_strength`, `score_solution_saturation`,
`score_purchase_intent`, `score_audience_dissatisfaction` — and rebalanced
`rules/scoring.yaml` from 10 to 14 weights (original ten scaled by 0.76, four
new at 0.06/0.04/0.08/0.06, sum exactly 1.0). All four were deliberately left
unwired from the live `scoring_pipeline.py`, with their wiring deferred to
Phase 3.6 ("Full Scoring Integration").

The frozen spec expected T21 to run "once all sources exist." The user directed
a scope change: skip the remaining adapter tasks (T16-T19 Phase 3 adapters,
plus T11/T12/T15 paused adapters) and wire scoring with the adapters already
built. The adapters we have already cover all four needed evidence types:
- **TREND**: Google Trends adapter
- **SEARCH_INTENT**: Search Demand (autocomplete) adapter
- **TRANSACTION**: Marketplace + Crowdfunding adapters
- **SOLUTION**: Amazon, App Store, HackerNews, Marketplace adapters
- **DISSATISFACTION**: Amazon reviews, App Store reviews, Reddit adapter

No weight changes needed — the T7 weights are correct for the scoring
dimensions regardless of how many adapters feed each type.

## Decisions

### Evidence-type counts via Creator → CreatorNiche → niche ResearchRuns

The four T7 functions take plain evidence counts as input. The pipeline needs
to know "how many TREND evidence rows exist for this creator's niches?" The
query path:

1. `CreatorNiche` → `niche_id` for the creator being scored
2. `ResearchRun` rows where `niche_id` matches (niche-discovery runs)
3. `Evidence` rows from those runs, grouped by `evidence_type`

This is loaded once per creator in `_load_creator_context` (not per cluster),
since niche-level evidence applies uniformly to all of a creator's clusters.
Added as a new `evidence_type_counts: dict[str, int]` field on `CreatorContext`.

### Behavioral change: 10 → 14 components

Before T21, the pipeline computed 10 components and `compute_score` normalized
by dividing by 0.76 (the sum of those 10 weights). After T21, all 14
components are computed and the normalizer is 1.0 (the full weight sum). This
means the same creator with the same evidence will get slightly different
aggregate scores — not because of new evidence, but because the normalization
denominator changed. `scoring.yaml` version bumped from 2.2.0 to 2.3.0 to
mark this.

### Graceful degradation when no niche evidence exists

If a creator has no `CreatorNiche` association (or no niche-discovery runs have
been performed), the evidence_type_counts dict is empty. The four functions
handle this correctly:
- `score_external_demand_strength(0, 0)` → 0.0
- `score_solution_saturation(0)` → 0.5 (neutral)
- `score_purchase_intent(0)` → 0.0
- `score_audience_dissatisfaction(0)` → 0.0

These are the "no evidence gathered" baselines, not assertions about the
market — matching the convention established by the original components
(e.g. `score_competition_saturation` returns 0.5 with no evidence).

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/intelligence/scoring_pipeline.py` | Added imports for `CreatorNiche`, `EvidenceType`, and 4 T7 scoring functions. Extended `CreatorContext` with `evidence_type_counts`. Added niche-evidence query in `_load_creator_context`. Added 4 new components in `_score_opportunity`. |
| `rules/scoring.yaml` | Version 2.2.0 → 2.3.0, updated comment to reflect T21 wiring. |
| `tests/workers/test_scoring_pipeline.py` | Updated `_creator_context()` for new field. Added 4 new unit tests: all-14-present, evidence-feeds-nonzero, zero-evidence-neutral, aggregate-uses-all-14-weights. |
| `tests/integration/test_scoring_pipeline.py` | Added 2 new integration tests: niche-evidence-flows-from-db, no-niche-evidence-gives-neutral. |

No migration. No changes to any adapter or to `engine.py`.

## Verification

- `mypy --strict` clean on `scoring_pipeline.py`.
- `ruff check` clean on all changed files.
- `tests/workers/test_scoring_pipeline.py` + `test_scoring_engine.py`: 60 passed.
- `tests/integration/test_scoring_pipeline.py`: 10 passed.
- Full `tests/workers/`: 616 passed (up from 612, the 4 new tests).
- Full `tests/integration/` + `tests/api/`: 348 passed, 1 pre-existing skip — unchanged baseline.

## Consequences

- The scoring pipeline now produces 14-dimensional scores for every creator.
  All existing adapters' evidence feeds into these dimensions automatically
  via `Evidence.evidence_type`.
- Future adapters (if any are unblocked) will contribute to scores without
  any pipeline changes — they just need to set `evidence_type` on their
  Evidence rows (which T2's adapter wiring already ensures).
- The `SCORING_RULE_VERSION` constant ("scoring_v2") is unchanged — it names
  the rule-set family, not the yaml version. The yaml's own version field
  (2.3.0) documents when the wiring changed.

## Note on scope change from frozen spec

The frozen spec expected T21 after T16-T19 (Phase 3 adapters). The user
directed skipping those tasks entirely: "let not add any more scrapers. let
use what we have and finish the app." This ADR records that direction change.
The weights were designed to be correct regardless of adapter count (missing
evidence → neutral/zero scores, `compute_score` normalizes by weight present),
so no weight adjustment was needed.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF, none of which T21 touched — the same pre-existing
dev-environment changes disclosed in every ADR since T4. Not staged as
part of this task's commit.
