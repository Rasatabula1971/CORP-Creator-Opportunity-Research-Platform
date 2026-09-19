# ADR-0046 — Wire T9 Handoff to T8's Approve Decision Path

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 finishing plan item 3, T9 (ADR-0039), T8 (ADR-0038)

## Context

T9 (ADR-0039) shipped `build_handoff_package()` in `corp/workers/handoff/
corp2_export.py` — a pure-read function that assembles the frozen Stage 3
handoff package (dossier, evidence trail, niche drill-down path, reviewer's
decision-gate notes) for an APPROVED dossier. It was shipped without any
transport mechanism, per its own design: "how CORP2 actually pulls or receives
it (a file drop, a pull endpoint, a queue) is a later task's concern."

T8's Approve branch in the decision endpoint had a stale comment saying T9 was
"not yet built." This wiring task connects them.

## Decisions

### Pull endpoint, not eager computation

The Stage 3 spec says "CORP1 never reaches into CORP2 directly, it only
produces a package CORP2 pulls." A pull-style `GET /dossiers/{id}/handoff`
endpoint matches this design:
- No migration or storage needed — the package is computed on-demand from
  existing tables.
- CORP2 (or any authorized client) pulls whenever it's ready.
- The endpoint checks dossier existence first (404 if not found), matching
  the codebase's convention for resource lookups. The remaining `ValueError`
  from `build_handoff_package` (non-approved status) maps to HTTP 422.

### Stale comment removed

The Approve branch in `record_dossier_decision` had a 4-line comment explaining
T9 wasn't built yet. Since T9 has been built and the endpoint now exists, the
comment was removed rather than updated — the endpoint's existence is the
documentation.

## Files changed

| File | Change |
| --- | --- |
| `corp/api/routes_ops.py` | Added `GET /dossiers/{dossier_id}/handoff` endpoint. Imported `build_handoff_package`. Removed stale T9 comment from Approve branch. |
| `tests/api/test_handoff_endpoint.py` | New: 3 integration tests — approved dossier returns full package, non-approved returns 422, unknown dossier returns 422. |

No migration. No model changes. No new dependencies.

## Verification

- `mypy --strict` clean on `corp/api/routes_ops.py`.
- `ruff check` clean on all changed files.
- `tests/api/test_handoff_endpoint.py`: 3 passed.
- Full `tests/api/`: 81 passed (up from 78, the 3 new tests).

## Consequences

- CORP2 (or any API consumer) can now pull the handoff package for any approved
  dossier via `GET /dossiers/{id}/handoff`.
- The Approve decision path itself remains unchanged — it sets `APPROVED` status
  and nothing more. The package is computed on-demand, not eagerly.
- Non-approved dossiers return 422 with a clear message, matching
  `build_handoff_package`'s own validation.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF — the same pre-existing dev-environment changes disclosed
in every ADR since T4. Not staged as part of this task's commit.
