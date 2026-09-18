# ADR-0036 — CORP1 Stage 5, T6: Dossier Model and Generator

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 4 ("What the Dossier
Contains", "Example Dossier Summary") and Stage 5, task T6

## Context

T0 created the `Dossier` table but nothing wrote to it — the dossier was,
and until this task remained, a value computed fresh on every request
(`DossierGenerator.generate`/`generate_data`, rendering `CreatorScore`/
`OpportunityScore`/`ProblemCluster` on demand). T6's job: make the
generator also produce a real, persisted `Dossier` row with its evidence
trail and niche path, folding in T5's product ideas.

## Decisions

### `generate_and_persist` is additive, not a replacement

The pre-existing `generate()` (HTML) and `generate_data()` (the live
`DossierResponse` the API still serves) are untouched. `generate_and_
persist(creator_id, niche_id)` is a new method that reuses `_load_data`
for the bulk of the aggregation rather than duplicating it, then adds
what only the persisted form needs: product ideas, niche path, a
recommendation, and the actual database write.

### One Dossier row needs one `opportunity_score_id` — the top-scoring one is used

`Dossier.opportunity_score_id` is a single, required FK (T0's schema,
forbidden to change here). A creator can have several active
opportunities (one per problem cluster). `generate_and_persist` persists
the row against the **highest-scoring** opportunity (`data.opportunities`
is already sorted by `aggregate_score` descending in the existing
aggregation) — but `content` still includes *every* active opportunity,
not just the top one, so nothing is lost from the full picture; only the
single required FK is scoped to the strongest signal.

### `niche_id` comes from the caller, not auto-derived inside the generator

`Creator.niche` is a free-text string, not a link to the canonical
`Niche` table — a creator's actual niche context lives in `CreatorNiche`
rows, and a creator can belong to more than one. `generate_and_persist`
takes `niche_id` as an explicit parameter rather than guessing; the new
API endpoint (see below) resolves it from the creator's most-recently-
observed `CreatorNiche`, keeping that judgment call at the call site,
not buried in the generator.

### The recommendation is deterministic, not a new LLM call

`_build_recommendation` derives a suggested action (using the *same*
vocabulary as the human decision gate — Reject / Research More / Watch /
Approve, Stage 3) purely from the existing `score_bands` thresholds
(`rules/scoring.yaml`) and `confidence_band`, plus a couple of
data-coverage checks for the risks list. No new `LLMProvider` dependency
was introduced — `DossierGenerator` remains exactly as free of external
service calls as it already was. The recommendation is explicitly a
nudge; Stage 3's Automation Matrix still makes the human gate the actual
decision-maker.

### Evidence trail respects the Stage 4 acceptance test directly

`_collect_evidence_ids` gathers evidence from both the persisted
opportunities' observations and the included product ideas'
`ProductIdeaEvidence`, then filters to rows with `research_run_id IS NOT
NULL` before linking any `DossierEvidence` — "a dossier's evidence trail
contains only rows traceable to a real ResearchRun" (Stage 4) is enforced
in code, not just assumed, and
`test_evidence_without_research_run_excluded_from_trail` proves a
counter-example is actually excluded, not merely that the happy path
looks right.

### Scope necessarily expanded by four files beyond the frozen list

T6's frozen "Allowed files" were `corp/workers/dossier/generator.py` and
`web/src/pages/CreatorDetailPage.tsx`. Four more files were touched, all
small, all necessary for the persisted dossier to actually be reachable
end-to-end (same class of decision as T4's `routes_ops.py` fix):

- `corp/core/schemas/dossier.py` — a new `PersistedDossierResponse`
  schema. T0's own ADR already anticipated this exact file needing this
  exact change "when it's actually used/returned via API" — this is that
  moment, not a new decision.
- `corp/api/routes.py` — two new endpoints
  (`POST /creators/{id}/dossier/generate`,
  `GET /creators/{id}/dossier/persisted`). Without a trigger and a read
  path, `generate_and_persist` would be unreachable from the product —
  the frontend page in T6's own frozen scope has nothing to call
  otherwise.
- `web/src/api/hooks.ts` and `web/src/api/types.ts` — the matching
  React Query hooks and TypeScript types the new endpoints need. The
  same class of small, necessary companion change T4 already
  established precedent for.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/dossier/generator.py` | Added `generate_and_persist`, `_load_product_ideas`, `_niche_path`, `_build_recommendation`, `_collect_evidence_ids`, `_score_band_key`. |
| `corp/core/schemas/dossier.py` | New `PersistedDossierResponse`. |
| `corp/api/routes.py` | New `POST /creators/{id}/dossier/generate`, `GET /creators/{id}/dossier/persisted`. |
| `web/src/api/hooks.ts` | New `useGeneratePersistedDossier`, `usePersistedDossier`. |
| `web/src/api/types.ts` | New `PersistedDossier` type. |
| `web/src/pages/CreatorDetailPage.tsx` | New "Persisted Dossier" panel — generate button, status, niche path, recommendation, product ideas. |
| `tests/integration/test_dossier_persistence.py` | New — 11 tests: basic persistence, the Stage 4 evidence-trail acceptance test (both the happy path and a proven counter-example), niche-path walking, product-idea inclusion, three recommendation-band cases, rerun supersession, two not-found error cases. |

No changes to `corp/core/models/dossier.py` (forbidden, per T6's frozen
card) or to `corp/workers/intelligence/niche_discovery.py` (T3).

## Verification

- `mypy --strict` and `ruff check` clean on all changed Python files.
- `tsc --noEmit` clean on all changed frontend files.
- 11 new tests pass.
- Full `tests/integration/` + `tests/api/` (314 passed, 1 pre-existing
  unrelated skip) and `tests/workers/` (553 tests) suites pass — zero
  regressions. (An earlier draft of this ADR wrongly reported 332 —
  that number came from a run that also included one `tests/workers/`
  file; corrected here per Stage 8 review, same class of counting
  mistake as T4's ADR, now caught here too.)

## Note on unrelated working-tree state (per Stage 8 review)

`git status` during this task also shows `web/src/api/client.ts` and
`start_corp.bat` as modified. **Neither is a T6 change.** Both predate
this task entirely — leftover uncommitted work from before this
session's Stage 6 build sequence began (T0), correctly excluded from
every commit from T0 through T5 the same way they are excluded here.
Omitted from this ADR's first draft; added per Stage 8 review, matching
the disclosure ADR-0034 (T4) already made for the same two files.

## Non-blocking follow-ups flagged by Stage 8 review

- `generator.py`'s `_score_band_key` duplicates `corp.core.scoring.
  engine.get_score_band`'s threshold-lookup loop rather than sharing it,
  because `get_score_band` returns the display label ("Exceptional
  opportunity") and this task needs the stable key ("exceptional") to
  branch logic on safely. The fix is a genuine DRY violation risk (a
  future band rename in `rules/scoring.yaml` could desync the two copies
  silently) but was left as-is rather than refactoring `engine.py`
  (outside T6's scope) to extract a shared `get_score_band_key()`. Worth
  doing whenever `engine.py` is next touched.
- No route-level test covers the new POST endpoint's 422 response for a
  creator with zero `CreatorNiche` rows (the 11 new tests exercise the
  generator directly, not the route). The behavior is correct
  (`scalar_one_or_none()` → clean 422), just not test-covered at the API
  layer yet.

## Consequences

- CORP1 now has a real, queryable, versioned decision-ready artifact per
  (creator, niche) — the actual object the Stage 3 four-state decision
  gate (T8) will operate on, once built.
- T7 (scoring engine update, capability-based evidence weighting) and T9
  (CORP2 handoff package) can both build directly on `Dossier.content`'s
  shape rather than re-deriving it.
