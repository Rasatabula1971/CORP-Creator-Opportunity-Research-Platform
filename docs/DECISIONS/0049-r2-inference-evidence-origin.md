# ADR-0049 — R2: LLM-derived Evidence rows carry `origin = INFERENCE`

**Status:** Accepted (Stage 8: ACCEPT, no blocking findings; Stage 9: accepted by user 2026-09-21, who explicitly ratified the product-idea deviation from T5's literal wording — see Decision, bullet 4)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R2; audit finding #4; spec
"Provenance Invariant (Frozen)" and Stage 4 acceptance "every Evidence row
has both evidence_type and origin set"

## Context

`Evidence.origin` (observation | inference) was added by migration
a7b8c9d0e1f2, and the three adapter-fed write paths set it to `OBSERVATION`
in b137205. Two pipelines persist an LLM claim as its own Evidence row —
`IntentPipeline` (the intent-classification rationale a `CommercialSignal`
points at) and `CompetitivePipeline` (the analysis a `Competitor` points at)
— and set neither `origin` nor `evidence_type`. `EvidenceOrigin.INFERENCE`
was therefore never used anywhere, which is precisely the case the spec's
invariant exists for ("the system must never silently present its own
inference as raw evidence"). Two docstrings (`product_idea.py`,
`product_ideation.py`) also still claimed the column "does not exist".

## Decision

- `intent_pipeline.py`: `origin = INFERENCE`, `evidence_type = PROBLEM` — the
  row is an inference *about the cluster's problem*, so it inherits the
  cluster's type rather than a commercial one (the commercial reading lives
  on `CommercialSignal.signal_level`, not on the evidence type).
- `competitive_pipeline.py`: `origin = INFERENCE`, `evidence_type = SOLUTION`
  — the row describes existing solutions (the competitive landscape).
- `corp/core/evidence/store.py::create_evidence`: `evidence_type` and
  `origin` become required keyword arguments (no callers exist; this stops
  the helper from being a future bypass).
- Product ideas deliberately do **not** write a synthetic inference row. An
  idea is a proposal grounded in observation rows, and its trail is
  `ProductIdeaEvidence` → the `origin = observation` rows that grounded it.
  This is a disclosed deviation from T5's literal wording ("traces to an
  `Evidence.origin = inference` row"); both docstrings now say so instead of
  claiming the column was removed.
- New static guard `tests/core/test_evidence_provenance_constructors.py`:
  AST-scans every `Evidence(...)` call under `corp/` and fails if either
  keyword is absent. This is the code-level half of the Stage 4 acceptance
  test; R3 adds the database-level half (`NOT NULL`).

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/intelligence/intent_pipeline.py` | Import + set `evidence_type=PROBLEM`, `origin=INFERENCE` |
| `corp/workers/intelligence/competitive_pipeline.py` | Import + set `evidence_type=SOLUTION`, `origin=INFERENCE` |
| `corp/core/evidence/store.py` | `evidence_type`/`origin` now required |
| `corp/core/models/product_idea.py` | Docstring corrected (column exists; deviation disclosed) |
| `corp/workers/intelligence/product_ideation.py` | Docstring corrected |
| `tests/core/test_evidence_provenance_constructors.py` | New AST guard |
| `tests/workers/test_competitive_pipeline.py` | Assert origin/type on the written row |
| `tests/integration/test_intent_pipeline.py` | Assert origin/type on the written row |

No migration. No model changes.

## Verification

- `ruff check` (E,F,I,N,W) clean on all eight changed files.
- `mypy --strict` clean on the five changed source files and the new test.
- `tests/core/test_evidence_provenance_constructors.py` +
  `tests/core/test_evidence_type_mapping.py` +
  `tests/workers/test_competitive_pipeline.py` +
  `tests/integration/test_intent_pipeline.py`: 190 passed.
- `tests/integration/test_product_ideation.py`: 8 passed (docstring-only
  change in that module).

## Consequences

- Every Evidence write path in `corp/` now sets both provenance fields; a new
  constructor call without them fails the test suite.
- Dossier consumers can distinguish raw source rows from LLM claims by
  `origin`; the frontend does not yet surface this (R7).
- R3 can now backfill the two inference `source_type`s
  (`intent_classification`, `competitive_analysis`) deterministically.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
