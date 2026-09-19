# ADR-0047 — Fix DossierGenerator Cross-Niche Opportunity Mismatch

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 finishing plan item 4, task_a4a49af1 (spawned from T10 review)

## Context

`DossierGenerator.generate_and_persist(creator_id, niche_id)` picks the globally
top-scored opportunity across ALL of a creator's clusters, regardless of which
niche that cluster's evidence came from. For a multi-niche creator, this means a
dossier labeled "Home Espresso" could reference a "Sourdough Baking" opportunity
as its primary `opportunity_score_id` — simply because that opportunity scored
higher overall.

The root cause: `ProblemCluster` and `OpportunityScore` have no `niche_id`
column. All pipelines (clustering, intent, scoring) operate at the creator
level, not per-niche. The niche connection only exists through the evidence
chain: `ProblemObservation.evidence_id` → `Evidence.research_run_id` →
`ResearchRun.niche_id`.

## Decision

### Evidence-chain filtering without schema changes

Added `_filter_niche_opportunities()` to `DossierGenerator`. For each
opportunity's observations, it checks whether any of their evidence traces to a
`ResearchRun` with the target `niche_id`. This is a single SQL query (join
Evidence → ResearchRun, filter by niche_id and evidence IDs).

If niche-relevant opportunities are found, the dossier uses the top one from
that filtered set. If none are found (common for creators whose evidence came
from creator-level research runs with no niche_id), it falls back to the global
top — same as the old behavior, which is correct for single-niche creators.

### Why no migration

Adding `niche_id` to `ProblemCluster` or `OpportunityScore` would require:
- A migration
- Modifying every pipeline that creates clusters/scores (clustering, intent,
  scoring, competitive)
- Backfilling existing data

This is disproportionate for a bug fix in a "finish the app" phase. The
evidence-chain approach solves the actual user-visible problem (wrong opportunity
in the dossier) with zero schema changes and one new query.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/dossier/generator.py` | Added `_filter_niche_opportunities()` method. Changed `generate_and_persist` to use niche-filtered top opportunity when available. |
| `tests/integration/test_dossier_persistence.py` | Added `test_niche_scoping_picks_niche_relevant_opportunity`: seeds a multi-niche creator with two opportunities at different scores and different niche research runs, verifies the dossier picks the niche-relevant one (0.60) over the global top (0.90). |

No migration. No model changes. No pipeline changes.

## Verification

- `mypy --strict` clean on `corp/workers/dossier/generator.py`.
- `ruff check` clean on all changed files.
- `tests/integration/test_dossier_persistence.py`: 12 passed (1 new).
- `tests/workers/test_dossier_generator.py`: 18 passed, no regressions.

## Consequences

- Multi-niche creators now get niche-relevant top opportunities in their
  dossiers, when the evidence chain links to niche-specific research runs.
- Single-niche creators and creators with only creator-level research runs
  (no niche_id on their ResearchRun) behave identically to before — the
  global top is the correct answer when there's no niche-scoping data.
- The registry re-scan scheduler (T10, now wired via ADR-0045) calls
  `generate_and_persist` per dossier — each dossier's niche_id will now
  scope correctly.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF — same pre-existing dev-environment changes.
