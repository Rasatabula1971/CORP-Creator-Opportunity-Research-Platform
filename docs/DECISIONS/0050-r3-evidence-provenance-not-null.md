# ADR-0050 — R3: Backfill Evidence provenance and enforce it at the database

**Status:** Accepted (Stage 8: ACCEPT, non-blocking findings folded into the text; Stage 9: accepted by user 2026-09-21)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R3; spec Stage 4 acceptance
"every Evidence row has both evidence_type and origin set"

## Context

R1 and R2 made every write path in `corp/` set `evidence_type` and `origin`,
and a static AST guard keeps it that way. The columns themselves were still
nullable, so the Provenance Invariant was enforced only by code. The user
chose (plan decision, 2026-09-21) to backfill and tighten to `NOT NULL` — the
database holds only test data, so the backfill cost is nil and the invariant
becomes a hard schema guarantee.

A pre-migration check found 265 rows in `corp` and 0 in `corp_test`, none
with a NULL in either column: the backfill is a safety net for other
environments, not a repair of this one.

## Decision

- **Migration `5f5732311984`** (revises `0c8be346208b`): backfill in three
  steps — `intent_classification` → INFERENCE/PROBLEM,
  `competitive_analysis` → INFERENCE/SOLUTION, everything else →
  OBSERVATION with `evidence_type` from `_PLATFORM_EVIDENCE_TYPE` by
  `lower(source_platform)` (the CASE is built from the model's dict at
  migration time, so there is one source of truth). If any row is still NULL
  afterwards the migration **raises**, naming the unmapped platforms, rather
  than guessing. Then `ALTER COLUMN ... SET NOT NULL` on both. Downgrade
  relaxes the constraints only.
- **Model**: both columns `Mapped[...]` non-optional, `nullable=False`;
  docstrings updated.
- **`require_evidence_type()`** (new, `evidence.py`): strict form used by the
  three legacy collect() paths (`collector.py`, `discovery.py`,
  `multi_discovery.py`). An unmapped platform now raises
  `ValueError("No evidence type mapped for platform 'x'; add it to …")`
  *before* the row reaches the session, instead of an opaque
  `NotNullViolation` at flush that would also poison the session for every
  later item. Failure mode per path (Stage 8 finding): `collector.py`
  re-raises and fails the run; `discovery.py` and `multi_discovery.py`
  catch per item, log at WARNING and count an item failure, so a wholly
  unmapped platform yields N warnings and a run that still completes — not
  swallowed, but not a hard stop either. `infer_evidence_type()` (lenient)
  is retained only as the helper behind `require_evidence_type()` and for
  tests; it has no read-side callers today.
- **Tests**: 28 `Evidence(` fixtures across 16 files now pass both fields.
  `test_stage4_models.py::test_evidence_type_optional_for_backward_compatibility`
  asserted the old nullable behaviour and is replaced by
  `test_evidence_provenance_fields_are_required` (parametrised over both
  columns, expects `IntegrityError`). `test_discovery.py`'s fake adapter
  spoke platform `"fake"`, which is intentionally unmapped; it now uses
  `"hackernews"` (six string updates, no logic change) — the test's subject
  is run/ledger provenance, not the platform name.

## Files changed

| File | Change |
| --- | --- |
| `migrations/versions/5f5732311984_r3_evidence_provenance_backfill_not_null.py` | New: backfill + NOT NULL (applied to `corp` and `corp_test`) |
| `corp/core/models/evidence.py` | Columns `nullable=False`; `require_evidence_type()`; docstrings |
| `corp/workers/acquisition/collector.py`, `discovery.py`, `multi_discovery.py` | Use `require_evidence_type` |
| `tests/core/test_evidence_type_mapping.py` | Test for `require_evidence_type` |
| `tests/integration/test_stage4_models.py` | Nullable test replaced by NOT-NULL test (+ fixtures) |
| `tests/integration/test_discovery.py` | Fake adapter platform → `hackernews` |
| 15 further test files (`tests/api/test_endpoints.py`, `test_handoff_endpoint.py`; `tests/integration/test_cluster_pipeline.py`, `test_corp2_export.py`, `test_dossier_persistence.py`, `test_dossier_pipeline.py`, `test_intelligence_pipeline.py`, `test_intent_pipeline.py`, `test_models_db.py`, `test_niche_candidates.py`, `test_niche_canonicalization.py`, `test_niche_verification.py`, `test_product_ideation.py`, `test_registry_rescan.py`, `test_scoring_pipeline.py`) | `Evidence(` fixtures gain `origin=` / `evidence_type=` |

## Verification

- `alembic upgrade head` applied cleanly to `corp` and `corp_test`; both at
  `5f5732311984 (head)`.
- `ruff check` (E,F,I,N,W) clean on all changed source files and on the
  test files listed by name above; the fixture-only test files carry a few
  pre-existing E501/F841 hits on lines not touched here.
- `mypy --strict` clean on `evidence.py`, the migration, and the three
  acquisition modules.
- `tests/integration/test_migration.py` (full downgrade/upgrade round-trip
  including this migration): passed as part of the runs below.
- Full suite, `python -m pytest tests/ -q` with the 7 known pre-existing
  failures deselected: **1257 passed, 1 skipped, 5 deselected** (0 failed;
  two of the seven deselect ids are not collected in this run, hence 5).
  Before R3's test-side changes the same command showed 6 failures, all in
  `test_discovery.py`, all from the unmapped `"fake"` platform.

## Consequences

- The database now rejects any Evidence row without provenance; the code
  guard (R2) and the schema guard agree.
- Any new adapter must be added to `_PLATFORM_EVIDENCE_TYPE` (R1's test
  enforces this for `KNOWN_PLATFORMS`) or it fails loudly on first collect.
- `tests/integration/test_campaign_pipeline_e2e.py` (already a known
  pre-existing failure, deselected) uses platform `"fakeniche"` and will
  need the same rename when that test is repaired.
- Follow-up worth its own task: `NormalizedContent` could carry an explicit
  `evidence_type` set by the adapter (it already knows which capability it
  implements), removing the platform-name lookup from the legacy paths
  entirely. Not done here — it touches `adapters/base.py` and every adapter.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
