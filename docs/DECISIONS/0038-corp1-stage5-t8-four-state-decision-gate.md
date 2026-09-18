# ADR-0038 — CORP1 Stage 5, T8: Four-State Decision Gate

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 3 "Human Decision
Gate" and Stage 5, task T8

## Context

T8's frozen scope lists two allowed files: `corp/api/routes_*.py` (a
decision endpoint) and `web/src/pages/CreatorDetailPage.tsx`. Its
acceptance criteria require the UI/API to expose exactly Reject /
Research More / Watch / Approve, with Research More creating "a new
`ResearchRun` at `depth + 1` via T3's engine" — matching the Stage 3
spec's own wording that Research More "automatically drills one level
deeper into the niche and re-queries all evidence sources for that
specific niche, then produces an updated dossier."

Research during the build (not assumption) found this criterion cannot
be met inside the frozen file list as written: T3's `RecursiveNiche
Discovery` has exactly one public entrypoint, `discover(campaign_id,
topic)`, which always starts a fresh recursion at depth 0 for a broad
topic. It has no way to resume drilling a specific, already-canonical
niche at its own depth + 1. Building that capability means changing
`corp/workers/intelligence/niche_discovery.py`, outside T8's allowed
files — the same kind of scope/reality mismatch T3 hit with `NicheCandidate.
lifecycle_status = excluded`. Per that precedent (see
`docs/DECISIONS/0033`), this was taken to the user directly rather than
resolved unilaterally. Presented with three options — expand scope into
the engine, approximate within the frozen file list (re-run `discover()`
seeded by the niche's name, losing the depth+1/parent-anchor semantics),
or ship Reject/Watch/Approve now and defer Research More's trigger — the
user chose to expand scope into the engine, as the most faithful option.

## Decisions

### Scope expansion: `corp/workers/intelligence/niche_discovery.py` (user-directed)

Added `RecursiveNicheDiscovery.research_more(niche_id, campaign_id)`: a
second public entrypoint, distinct from `discover()`, that:

- Looks up the most recently **promoted** `NicheCandidate` for this niche
  (`NicheCandidate.niche_id == niche_id` **and**
  `NicheCandidate.status == PROMOTED`, latest by `created_at`) to use
  as `parent_candidate_id`, anchoring new candidates as its children —
  or falls back to no anchor (`parent_candidate_id=None`) with
  `niche.depth + 1` if the niche has no traceable candidate lineage
  (e.g. seeded outside the discovery pipeline).
- Calls the same private `_drill()` step `discover()` uses internally,
  seeded with the niche's own `canonical_name` as the keyword, at
  `depth = (parent_candidate.depth or niche.depth) + 1`.
- Bypasses the registry-freshness skip (`_is_registry_fresh`) that
  `_drill()` would otherwise apply — added a `skip_registry_check`
  keyword-only parameter to `_drill`, defaulting to `False` so
  `discover()`'s existing behavior (and every existing test) is
  unchanged. A human explicitly requesting Research More must not be
  silently no-op'd because the niche was scanned recently; only this
  top-level call sets it `True` — any further auto-recursion triggered
  from inside it still respects the registry normally.

No migration: `Niche.depth`, `NicheCandidate.parent_candidate_id` /
`.depth` / `.niche_id`, and `ResearchRun.niche_id` already exist (T0).

### The decision endpoint: `corp/api/routes_ops.py` (in scope)

New `POST /dossiers/{dossier_id}/decision`, separate from the existing
`POST /creators/{creator_id}/decisions` (Gate A, creator-status-scoped,
untouched — it lives in `routes.py`, which doesn't match `routes_*.py`
and is outside this task's scope regardless). `DossierDecisionRequest`/
`DossierDecisionResponse` are defined locally in `routes_ops.py`
(matching that file's existing pattern of request/response models local
to the API, e.g. `CampaignPipelineRequest`), not added to
`corp.core.schemas.workflow`, keeping the change inside the frozen
route-file scope.

`decision: DecisionType` is the only validation needed for "exposes
exactly Reject / Research More / Watch / Approve" — `DecisionType` has
precisely those four members (T0), so Pydantic rejects anything else
with a 422 before the handler runs; no manual allow-list check.

Every call records a new `HumanDecision` row
(`creator_id=dossier.creator_id, dossier_id=dossier.id, gate=Gate.GATE_D,
...`) — never updates one. `Gate.GATE_D` is this task's own choice: the
`Gate` enum (A–E) had no letter assigned to a dossier-level gate before
this task; B/C/E remain unused/reserved.

Per-outcome effects:

- **Reject** → `Dossier.status = REJECTED`. No other effect.
- **Watch** → `Dossier.status = WATCHING`. No other effect (matches the
  acceptance criterion literally).
- **Approve** → `Dossier.status = APPROVED`. No direct call into T9 (not
  yet built) — `Dossier.status == APPROVED` is what T9's CORP2 export job
  will query for once it exists, matching the spec's own CORP1/CORP2
  boundary ("CORP1 never reaches into CORP2, only produces a package
  CORP2 pulls").
- **Research More** → looks up the dossier's niche's `CampaignNiche` (422
  if none — a dossier's niche with no campaign association cannot be
  re-drilled via a campaign-scoped run); 409 if a job is already running
  for that campaign (matching `start_campaign_pipeline`'s existing
  conflict check). Sets `Dossier.status = RESEARCH_MORE_IN_PROGRESS`
  (already an existing `DossierStatus` member, T0), creates a
  `JobRegistry` job, and dispatches `_run_research_more(niche_id,
  campaign_id)` via `BackgroundTasks` — a small work function defined
  directly in `routes_ops.py` (not added to `corp.api.jobs`, to avoid a
  further scope expansion) that mirrors `jobs.run_campaign_pipeline`'s
  `discover` branch but calls the new `research_more()` instead.

### Frontend: `CreatorDetailPage.tsx` + two necessary companions

New `DossierDecisionPanel` component, rendered alongside the existing
`PersistedDossierPanel` (T6) and gated the same way the existing Gate A
`DecisionPanel` is (hidden once `persisted.status` is `approved` or
`rejected`). Labeled "Dossier Decision" to read as clearly distinct from
the existing "Gate A Decision" panel.

Necessarily touched two files beyond the frozen list, same pattern as
T4/T6: `web/src/api/hooks.ts` (new `useRecordDossierDecision`) and
`web/src/api/types.ts` (new `DossierDecisionType`/`DossierDecisionInput`/
`DossierDecisionResult`) — a new mutation hook needs a typed request/
response shape, and this codebase's convention keeps those in `types.ts`/
`hooks.ts`, not inlined in the page component.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/intelligence/niche_discovery.py` | Added `RecursiveNicheDiscovery.research_more()`; added `skip_registry_check` (default `False`) to `_drill()`. Scope expansion beyond T8's frozen list, user-directed (see Context). |
| `corp/api/routes_ops.py` | New `POST /dossiers/{dossier_id}/decision`, local `DossierDecisionRequest`/`DossierDecisionResponse`, `_run_research_more()` work function. |
| `web/src/pages/CreatorDetailPage.tsx` | New `DossierDecisionPanel`, wired in next to `PersistedDossierPanel`. |
| `web/src/api/hooks.ts` | New `useRecordDossierDecision`. |
| `web/src/api/types.ts` | New `DossierDecisionType`/`DossierDecisionInput`/`DossierDecisionResult`. |
| `tests/integration/test_niche_discovery.py` | 6 new tests for `research_more()` (depth+1 anchoring, fallback with no candidate lineage, registry-freshness bypass, niche/campaign-not-found, and — added in the Stage 8 REVISE round — that a more recent MERGED candidate for the same niche is never picked as the anchor). |
| `tests/api/test_dossier_decision_endpoint.py` (new) | 9 tests: one per decision outcome (reject/watch/approve/research_more), the 422 no-campaign-association case, the 409 conflict case, 404, invalid-value 422, and append-only. |

No changes to `corp/core/models/dossier.py`, `corp/core/models/
workflow.py`, or `corp/api/jobs.py` — matching the "no changes to
HumanDecision/Dossier models" constraint, and keeping the new work
function local to `routes_ops.py` rather than expanding into `jobs.py`.

## Stage 8 review: one REVISE finding, fixed

Independent review confirmed the scope-expansion justification (item 1),
`skip_registry_check` backward compatibility, the endpoint's validation-
before-mutation ordering, and both scrutinized tests as sound — but
found a real correctness bug in `research_more()`'s parent-candidate
lookup: it filtered only on `NicheCandidate.niche_id == niche_id`, with
**no `status == PROMOTED` filter**. Since `niche_id` is populated by
*both* the PROMOTED branch of canonicalization (this candidate created
the niche) and the MERGED branch (some other candidate, possibly from an
unrelated campaign, was folded into this niche), a more recent MERGED
row for the same niche — from a different drill lineage entirely — could
silently be picked as the depth+1 anchor instead of the niche's actual
PROMOTED candidate. Fixed by adding the missing `status ==
NicheCandidateStatus.PROMOTED` condition, with a new regression test
(`test_research_more_ignores_a_more_recent_merged_candidate`) that
constructs exactly this scenario — an older PROMOTED candidate and a
newer MERGED one for the same niche at a different depth — and asserts
the drill anchors on the PROMOTED one.

## Verification

- `mypy --strict` and `ruff check` clean on `corp/api/routes_ops.py` and
  `corp/workers/intelligence/niche_discovery.py` (re-checked after the
  Stage 8 fix).
- `ruff check` clean on both new/changed test files.
- `tests/integration/test_niche_discovery.py`: 19 passed (13 pre-existing
  + 6 new, including the post-review regression test) — the pre-existing
  13 are unchanged, confirming `skip_registry_check`'s default preserves
  `discover()`'s behavior exactly.
- `tests/api/test_dossier_decision_endpoint.py`: 9 passed.
- `npx tsc --noEmit` in `web/`: clean, no errors.
- Full `tests/workers/`: 575 passed, zero failures — re-run after the fix.
- Full `tests/integration/` + `tests/api/`: 329 passed (up from 328,
  the new regression test), 1 pre-existing unrelated skip, zero
  regressions — re-run after the fix.

## Consequences

- T9 (CORP2 handoff export) can now assume `Dossier.status == APPROVED`
  is a reliable signal to query for, set exactly once by this task's
  Approve path.
- `RecursiveNicheDiscovery` now has two public entrypoints
  (`discover`, `research_more`) instead of one — any future change to
  `_drill()`'s signature must keep both call sites in mind.
- `Gate.GATE_D` is now a real, used value. B/C/E remain unassigned;
  a future task introducing another distinct gate should pick deliberately
  rather than reusing D.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF, none of which T8 touched — pre-existing dev-
environment changes from earlier in this session, unrelated to this
task. Not staged as part of this task's commit.
