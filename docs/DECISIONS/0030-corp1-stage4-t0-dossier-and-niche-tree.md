# ADR-0030 — CORP1 Stage 4, T0: Niche Drill-Down Tree + Dossier Model

**Status:** Accepted
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 4 (Architecture Gate) and Stage 5, task T0

## Context

The CORP1 product spec froze a recursive niche-drilling pipeline (broad topic
→ main niche → inter-niche → sub-niche, capped at depth 3) and a four-state
human decision gate (Reject / Research More / Watch / Approve) producing a
persisted, handoff-ready dossier. None of that had schema support:

- `Niche.parent_domain` is a plain string, not a real tree — no self-FK, no depth.
- `NicheCandidate` had no tree structure either.
- `Evidence` had no field recording which capability-provider interface
  (ProblemProvider, TrendProvider, etc.) produced a row.
- `HumanDecision.decision` only had `APPROVE / REJECT / WATCH` — no
  `RESEARCH_MORE`.
- No `Dossier` table existed at all. The dossier is currently computed on
  the fly by an endpoint that assembles `DossierResponse`
  (`corp/core/schemas/dossier.py`) from Creator/CreatorScore/
  OpportunityScore/ProblemCluster at request time.

## Decision

### 1. Reuse, don't duplicate, existing exclusion machinery

The frozen CORP1 spec called for a niche `excluded` state. `Niche` already
has exactly this: `policy_class: NichePolicyClass` (`standard / restricted /
excluded`), added in Slice 2 (docs/DECISIONS/0002) specifically so that "the
rules that assign a policy class" could be filled in by "a later,
discovery-facing slice." That slice is CORP1's T3. **No schema change was
needed for exclusion** — this migration adds none. The CORP1 spec's Stage 4
section is corrected accordingly (it originally proposed adding `excluded`
to `NicheLifecycleStatus`, which would have duplicated `policy_class`).

### 2. Niche and NicheCandidate: add a real tree

Both gain `parent_<x>_id` (self-referential FK, nullable) and `depth`
(integer, default 0). `Niche.parent_domain` stays as a display label only.
`last_researched_at` / `next_recheck_at` (already on `Niche`) are reused
directly as the CORP1 research registry's re-scan fields — no separate
registry table, matching the "existing machinery is retained and modified,
not duplicated" approach the Acquisition system used for the same kind of
decision.

`NicheCandidateStatus` gains `DRILLING`, so a candidate mid-recursion is
distinguishable from a finished `STAGED` one.

### 3. Evidence: evidence_type only, not evidence_type + origin

The frozen spec called for an `origin: observation | inference` field on
`Evidence`, mirroring the Acquisition system's provenance invariant. Reading
the codebase changed this: `ProblemObservation.is_inferred` already tracks
exactly this distinction, at the layer where inference actually happens.
`Evidence` rows are raw source data by construction (`raw_text`,
"Append-only evidence store") — they are never themselves an LLM inference.
Adding `origin` to `Evidence` would have been a field that was always
`observation`, in the one table `is_inferred` is not needed. **Only
`evidence_type` was added** (nullable, one of the eight capability-provider
values); the observation/inference distinction stays where the codebase
already puts it — per derived artifact (`ProblemObservation.is_inferred`,
`NicheCandidate.naming_method`, and the new `ProductIdea`/`Dossier` models
land the same way in later tasks).

### 4. HumanDecision: RESEARCH_MORE + dossier_id

`DecisionType` gains `RESEARCH_MORE`. `HumanDecision` gains a nullable
`dossier_id` FK. `creator_id` stays `NOT NULL` and unchanged — a decision
still always names the creator it concerns; `dossier_id` is additive.
`corp.core.state.gates._DECISION_TO_STATUS` (the existing creator-status gate
map) is untouched by this migration and does not yet have a `RESEARCH_MORE`
entry — wiring that up, and building the dossier-level gate the spec
describes, is T8's job, not T0's.

### 5. New: Dossier + DossierEvidence

`Dossier` (`creator_id`, `niche_id`, `opportunity_score_id`, `research_run_id`,
`content` JSONB, `status`, `generated_at`, `superseded_at`) persists what was
previously a request-scoped computed value. This is a deliberate shift from
"computed view" to "stored artifact with an id" — required because the
decision gate (T8) needs something stable to decide on, and the CORP2
handoff (T9) needs an immutable snapshot to hand off, neither of which a
value that only exists for one request's duration can provide.
`DossierEvidence` is a join table to the evidence trail, following the exact
same pattern as `NicheCandidateEvidence`.

`content`'s shape intentionally mirrors the existing `DossierResponse`
schema so T6 (the dossier generator) has a direct, low-friction mapping from
the computed response it replaces.

**Deliberately not added: a `niche_path` column.** The frozen spec lists
`niche_path` as part of what `Dossier` carries for the CORP2 handoff package.
It is not a new fact to store — Niche now has a real tree
(`parent_niche_id`, this same migration), so the full drill-down path is
always derivable by walking it from `Dossier.niche_id`. Storing it as a
column would be a denormalized cache of something the schema already
answers, and no call site exists yet to say when it should be
(re)computed. Producing it is T9's job (the CORP2 handoff builder), by
walking `Niche.parent_niche_id`, not T0's — T0 only had to make the walk
possible, which the tree columns already do.

## Files changed

| File | Change |
| --- | --- |
| `corp/core/models/niche.py` | Added `parent_niche_id`, `depth`, self-relationship. |
| `corp/core/models/niche_candidate.py` | Added `parent_candidate_id`, `depth`, self-relationship, `DRILLING` status. |
| `corp/core/models/evidence.py` | Added `EvidenceType` enum + nullable `evidence_type` column. |
| `corp/core/models/workflow.py` | Added `RESEARCH_MORE` to `DecisionType`; added nullable `dossier_id` to `HumanDecision`. |
| `corp/core/models/dossier.py` | New — `Dossier`, `DossierEvidence`, `DossierStatus`. |
| `corp/core/models/__init__.py` | Registered new exports. |
| `migrations/versions/c64b0f9a5c18_stage4_dossier_and_niche_tree.py` | New migration. |
| `tests/integration/test_stage4_models.py` | New — 34 tests covering tree traversal, DRILLING, evidence_type, Dossier/DossierEvidence, RESEARCH_MORE, backward compatibility of all nullable additions, and every member of `EvidenceType`/`DossierStatus`/`NicheCandidateStatus`/`DecisionType` round-tripping through the ORM individually. |

## Verification

- `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped
  cleanly against both `corp_test` and the local dev `corp` database.
- `mypy --strict` clean on all changed/new model files.
- 34 new tests pass (parametrized so every new/touched enum member is
  independently exercised, per T0's "every new enum value is reachable
  from the ORM" acceptance criterion); the 94 pre-existing tests across
  `test_models_db.py`, `test_migration.py`, `test_niche_candidates.py`,
  `test_niche_canonicalization.py`, `test_niche_qualification.py`, and
  `test_niche_verification.py` all still pass unmodified — no regressions.

## Consequences

- T1 (capability interfaces) and T3 (recursive niche discovery) can now
  target real columns instead of speculative ones.
- T8 (four-state decision gate) has a `RESEARCH_MORE` value and a
  `dossier_id` to build against, but still needs to extend
  `corp.core.state.gates` (or add a parallel dossier-level gate) — flagged
  here so it isn't missed.
- `evidence.evidence_type` and `human_decisions.dossier_id` are `NULL` for
  every pre-Stage-4 row. This is intentional and permanent — Postgres enum
  values (`DRILLING`, `RESEARCH_MORE`) cannot be removed by a downgrade
  either; a downgrade drops the new columns/tables but leaves those enum
  values defined and unused, matching the existing convention from
  docs/DECISIONS's `PAGE` content-type precedent.
