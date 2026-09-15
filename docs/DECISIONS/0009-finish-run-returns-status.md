# finish_run returns a status; a fully failed run is kept

**Status:** ACCEPTED (2026-09-14)
**Date:** 2026-09-14
**Trigger:** Twice in live runs a research run whose every unit failed vanished from the
database: Slice 7's Reddit 403 (`docs/DECISIONS/0007`, "latent flaw") and the provider
pool's run #5 (`docs/DECISIONS/0008`, item 5). Both times `finish_run` marked the row
`failed`, then raised `PipelineFailureError`; the exception skipped the caller's commit
and the session rollback erased the row. Research memory (§13) was lost exactly when it
mattered most — a run that documents *why* nothing came back.

## What changed

- `corp/workers/intelligence/runs.py`
  - `finish_run` never raises. It resolves `completed` / `partial` / `failed` from the
    stats as before, logs a failed run at ERROR, flushes, and returns the run. The
    status is the signal; callers read it.
  - `PipelineFailureError` is deleted (nothing raised it but `finish_run`).
  - `stage(...)` takes an optional `run`. On normal exit it restores the creator's
    previous status when `run.status == "failed"`, and advances to `done` otherwise.
    A stage that produced nothing must not leave the creator looking as if it had —
    before, that guarantee came for free from the exception path. Exceptions still
    restore, and callers that pass no `run` behave exactly as before.
- Call sites pass `run=run`: `collector.py`, `pipeline.py`, `cluster_pipeline.py`,
  `scoring_pipeline.py`. `intent_pipeline.py` and `discovery.py` do not use `stage`;
  `discovery.py` already returned `finish_run`'s result and now honours its own
  "never raises" contract in the all-items-fail case too.
- `corp/workers/orchestrator.py` — a local `step(run)` appends, **commits**, and stops
  the chain when a stage's run is `failed`: the report gets that run and the creator's
  (restored) status, and the rest of the stages are not attempted. Before, the chain
  relied on the exception to stop and never saw the failed run at all. Partial runs
  continue, as before.

## Tests

- `tests/workers/test_runs.py`: the raise test is flipped
  (`test_finish_run_all_failed_returns_failed_run_without_raising`); four new `stage`
  tests cover restore-on-failed-run, advance-on-partial, no-`run` compatibility, and
  restore-on-exception. 14 passed.
- `tests/integration/test_intelligence_pipeline.py::test_pipeline_failure_marks_run_failed`
  and `tests/integration/test_intent_pipeline.py::test_intent_pipeline_failure_marks_run_failed`
  no longer expect an exception; they assert the returned run is the persisted row,
  `failed`, with the error and a completion time. Both pass against Supabase.
- Non-DB suite 280 passed; DB integration suite 99 passed + the 2 flipped tests
  (the only failures in the full 101 run were these two, before the flip);
  ruff clean and mypy clean on every changed file; import-linter 2 kept.

## Not changed

- `fail_run` (an *exception* inside a stage) still re-raises after marking the row —
  that is a crash, not a result, and the caller decides what to do with it. The
  orchestrator's docstring now says both paths keep the run row.
- Formatting drift flagged by `ruff format --check` in `collector.py`, `pipeline.py`,
  `runs.py`, `scoring_pipeline.py` predates this change and is left alone.
- No orchestrator integration test exists; the stop-on-failed path is covered by the
  unit tests of its two building blocks (`finish_run`, `stage`) and by reading. Worth a
  test when the orchestrator next changes.
