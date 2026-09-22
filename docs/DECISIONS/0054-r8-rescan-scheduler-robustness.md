# ADR-0054 — R8: Re-scan scheduler — clock on success only, savepoint per dossier, resurface only on change

**Status:** Accepted (Stage 8: ACCEPT, two non-blocking findings applied; Stage 9: accepted by user 2026-09-21, who chose to schedule evidence re-collection on Watch expiry as its own task — plan R12 — rather than fold it in here)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R8; audit findings #7, #8;
T10's open product question (ADR-0040, "should unconditional resurfacing
to PENDING_REVIEW happen even with unchanged content?")

## Context

`rescan_watched_dossiers` (T10) advanced every due niche's
`next_recheck_at` by `recheck_days` *before* regenerating, so a dossier
whose regeneration failed was silently deferred a quarter with
`last_researched_at` untouched. The failure handler caught the exception
but not the session state: a database error inside `generate_and_persist`
left the shared session in pending-rollback, so every later dossier in the
batch failed and the final `flush()` discarded the successes (the existing
"one failing dossier" test only exercised a Python-level `ValueError`
raised before any flush). And every regeneration resurfaced to
`PENDING_REVIEW` unconditionally, even when nothing had changed — the
product question T10's review left open.

## Decision

- **Savepoint per dossier.** Each regeneration runs in
  `async with session.begin_nested()`. A DB error rolls back only that
  dossier's savepoint; the session stays usable for the rest of the batch
  and the caller's commit.
- **Clock advances on success only.** `last_researched_at = now` and
  `next_recheck_at = now + recheck_days` are set inside the savepoint
  after a successful regeneration. On failure `next_recheck_at = now +
  retry_days` (default 1): a transient error is retried tomorrow rather
  than in 90 days, and a persistent one does not log every hourly tick.
  `retry_days` is a keyword parameter with the same injection style as
  `recheck_days`; the scheduler class uses the default.
- **Resurface only on change.** `content_fingerprint()` hashes the dossier
  `content` JSONB with volatile keys (`generated_at`) removed. If the
  regenerated content's fingerprint equals the watched dossier's, the new
  row is set back to `WATCHING` and counted in `RescanStats.unchanged`
  (still inside `rescored`, since the scan itself succeeded). Otherwise
  T6's default `PENDING_REVIEW` stands and the dossier resurfaces. This
  resolves T10's product question in favour of "only when the evidence
  moved". The optimistic pre-advance that guarded against a concurrent
  tick is dropped: ticks are sequential within the one in-process
  scheduler.

Not done here (raised at this gate, decided 2026-09-21): re-querying
evidence sources on re-scan. The scheduler still regenerates from the
current `OpportunityScore`, so "the evidence strengthened" is only
detectable if something else re-ran research and scoring in the meantime
— today nothing does, so most re-scans will report `unchanged`. That is
correct but not yet what the Watch state promises; it becomes plan task
**R12** (needs a Stage 3/4 design pass: chaining `research_more` + the
creator research pipeline + scoring before regeneration, per-tick cost
limits, and a numeric definition of "strengthened").

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/scheduler/registry_rescan.py` | `content_fingerprint`; `RescanStats.unchanged`; `retry_days`; savepoint; clock-on-success; module docstring |
| `tests/integration/test_registry_rescan.py` | Three tests: unchanged content stays WATCHING on the second pass; a failed dossier is retried after `retry_days` with `last_researched_at` untouched; a foreign-key violation inside one dossier (monkeypatched `generate_and_persist`) rolls back only that dossier, the other regenerates, and the session commits |

No migration. No model changes.

## Verification

- `ruff check` (E,F,I,N,W) clean on both files; `mypy --strict` clean on
  the source file.
- `tests/integration/test_registry_rescan.py`: 11 passed (3 new; the
  pre-existing eight, including `test_niche_next_recheck_at_advanced_after_rescore`
  and `test_watched_dossier_past_recheck_date_gets_rescored`, unchanged).
- Full suite, `python -m pytest tests/ -q` with the 7 known pre-existing
  failures deselected: **1275 passed, 1 skipped, 5 deselected** (0 failed).

## Consequences

- A watched dossier whose evidence has not moved no longer re-enters the
  human queue every `recheck_days`; the human sees it again only when the
  content changed.
- A regeneration failure is visible (WARNING log, `failed` count) and
  retried the next day; it can no longer push a niche a quarter into the
  future unnoticed.
- One bad dossier can no longer wipe out the batch's successful
  regenerations.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
