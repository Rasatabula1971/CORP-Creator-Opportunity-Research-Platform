# ADR-0055 — R9: Gate A returns 422 for an invalid decision or foreign opportunity score

**Status:** Accepted (Stage 8: ACCEPT, non-blocking only — plan row corrected to name `routes.py`; a Gate-A-specific decision enum on `DecisionCreate` carried to R10; Stage 9: accepted by user 2026-09-21)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R9; audit finding #5

## Context

`record_gate_a_decision` (`corp/core/state/gates.py`) raises `ValueError`
in two cases: the decision is not one Gate A accepts (`DecisionCreate`
admits `research_more`, which belongs to the dossier gate), or
`opportunity_score_id` does not belong to the creator. `POST
/creators/{id}/decisions` did not catch it and `corp/api/errors.py` has no
`ValueError` handler, so both fell through to the catch-all and returned a
500 with a generic body — the client could not tell a bad request from a
server fault, and the log recorded an "unhandled error" for what is
ordinary input validation.

## Decision

Catch `ValueError` at the route and raise `HTTPException(422, str(exc))`.
Route-level rather than a global `ValueError → 422` handler: a blanket
mapping would turn genuine programming errors anywhere in the request
path into 422s and hide them. `InvalidTransitionError` keeps its own 409
handler. The 422 body carries `error.code = "validation_error"` via the
existing `_STATUS_CODES` table, matching request-validation failures.

## Files changed

| File | Change |
| --- | --- |
| `corp/api/routes.py` | `create_decision`: `try/except ValueError` → 422 |
| `tests/api/test_endpoints.py` | Two tests: `research_more` at Gate A → 422 with the gate's message and no status transition; foreign `opportunity_score_id` → 422, no transition |

## Verification

- `ruff check` (E,F,I,N,W) clean on `routes.py`; the test file carries two
  pre-existing F841 hits (`creator` assigned but unused at lines 194 and
  365), not touched here — scheduled for R11.
- `mypy --strict` clean on `routes.py`.
- `tests/api/test_endpoints.py`: 20 passed (2 new).
- Full suite, `python -m pytest tests/ -q` with the 7 known pre-existing
  failures deselected: **1277 passed, 1 skipped, 5 deselected** (0 failed).

## Consequences

- The frontend can branch on 422 vs 500 for Gate A; a wrong decision type
  is no longer logged as an unhandled server error.
- The two known pre-existing `tests/api` failures (message-vs-type-name
  assertions in `test_ops_no_db.py` / `test_provider_health.py`) are
  unrelated and remain for R11.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
