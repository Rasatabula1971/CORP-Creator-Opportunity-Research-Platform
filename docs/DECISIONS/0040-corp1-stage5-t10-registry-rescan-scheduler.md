# ADR-0040 — CORP1 Stage 5, T10: Registry Re-scan Scheduler

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 4 Architecture
Invariants and Stage 5, task T10

## Context

T10's frozen scope is one new file: `corp/workers/scheduler/
registry_rescan.py`. No migration. Acceptance criteria: any
`Dossier.status = watching` whose `Niche.next_recheck_at` has passed is
automatically re-scored within 24 hours, "satisfying the Stage 4
acceptance test" — read directly from Stage 4's own Architecture
Invariants list: "Watched dossiers are automatically re-scored within
24 hours of their niche's `next_recheck_at` passing, with no manual
action." Runs as an in-process scheduled job, no new queue
infrastructure. Tests: a time-travel test (mocked clock) asserting a
watched dossier past its recheck date gets re-scored and a fresh one
does not. No "Forbidden" bullet on this task card, unlike T8/T9.

## Decisions

### What "re-scored" means: regenerate via T6's existing generator

The Dossier lifecycle table (Stage 4) labels `watching` as an
"auto-rescore loop," and the Human Decision Gate text (Stage 3) frames
Watch as "parked... so it can resurface on its own if the evidence
strengthens." This task does not collect new evidence itself — that
already happens on whatever cadence drives `OpportunityScore`/
`ResearchRun` updates elsewhere in the pipeline. Its job is narrower and
fully expressible with existing machinery: notice a watched niche is
due, call `DossierGenerator.generate_and_persist(creator_id, niche_id)`
(T6) to render a fresh dossier off whatever is *currently* the latest
`OpportunityScore`, and let T6's existing latest-wins convention
supersede the old watched row. `generate_and_persist` defaults a new
dossier's status to `PENDING_REVIEW` — so a re-score that reveals a
strengthened opportunity naturally "resurfaces" it into the human review
queue, exactly matching the spec's own phrasing, with zero new logic for
that specific behavior.

This reuses T6 entirely rather than inventing new scoring/rendering
logic — the same "reuse before you build" pattern established since T2.

### Closing the loop: advancing `Niche.next_recheck_at`

Not spelled out explicitly in the acceptance criteria, but required for
correctness: without advancing the niche's `next_recheck_at` after a
re-scan, every subsequent tick would immediately re-match the same niche
again, re-scoring it in a tight loop. `rescan_watched_dossiers` sets
`Niche.last_researched_at = now` and `Niche.next_recheck_at = now +
recheck_days` for every niche it successfully re-scores — mirroring the
Architecture Invariant "a niche's `next_recheck_at` is always set on
scan completion" (a re-scan is itself a completion). `recheck_days`
defaults from the same `rules/niche_discovery_prompt.yaml` T3's
`DiscoveryConfig` already reads it from (90 days) — one source of truth
for the registry's cadence, not a second hardcoded constant.

### The scheduler itself: `asyncio`, no new dependency

"In-process scheduled job, no new queue infrastructure" is implemented
as a plain `asyncio.create_task` loop (`RegistryRescanScheduler`, hourly
default tick — comfortably inside the 24-hour SLA with margin for a
missed tick) — no Celery/RQ/cron, and no new third-party scheduling
library either, since a bare `asyncio` loop is sufficient and adds zero
dependency surface. `start()`/`stop()` are provided but nothing calls
`start()` yet: wiring it into application startup would mean touching
`corp/api/app.py`, outside T10's frozen one-file scope — left to
whichever later task wires it in, the same precedent T7 (scoring
functions, unwired from the pipeline) and T9 (handoff package, unwired
from any transport) already established. The tested, callable logic
(`find_due_watched_dossiers`, `rescan_watched_dossiers`) is the part
this task's frozen scope actually asks for.

### No `ResearchRun` created for a re-scan pass

Every other pipeline in this codebase creates a `ResearchRun` for
provenance. Deliberately not done here: no `RunType` enum member fits
"registry rescan," and adding one would mean editing `corp/core/models/
workflow.py` — outside T10's frozen scope, and "Migration: none" rules
out a schema change regardless (`RunType` is a plain `String` column
today, not a native Postgres enum, but adding a value is still a model
change this task isn't allowed to make). A lightweight local
`RescanStats` dataclass (`checked`/`rescored`/`failed`) covers what this
task needs without borrowing `PipelineStats`' run-lifecycle machinery
that assumes a `ResearchRun` exists.

### Time-travel test: dependency-injected `now`, not monkeypatched `datetime`

`find_due_watched_dossiers`/`rescan_watched_dossiers` both accept an
optional `now: datetime | None` parameter (defaulting to real time).
Tests pass a fixed `now` directly rather than monkeypatching
`datetime.now` globally — deterministic, and it cannot leak into any
other test running in the same process, unlike a global monkeypatch.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/scheduler/__init__.py` (new) | Empty, matches sibling worker packages' convention. |
| `corp/workers/scheduler/registry_rescan.py` (new) | `RescanStats`, `find_due_watched_dossiers()`, `rescan_watched_dossiers()`, `RegistryRescanScheduler`. |
| `tests/integration/test_registry_rescan.py` (new) | 8 tests: the frozen time-travel test (watched-past-due gets rescored, fresh does not), non-watching/already-superseded dossiers ignored, `next_recheck_at` advancement, and one-failure-doesn't-block-the-batch. |

No changes to any model file or migration.

## Verification

- `mypy --strict` clean on `corp/workers/scheduler/registry_rescan.py`.
- `ruff check` clean on the new module and the new test file.
- `tests/integration/test_registry_rescan.py`: 8 passed.
- Full `tests/integration/` + `tests/api/`: 346 passed (up from T9's
  337, the 8 new tests + 1 pre-existing unrelated skip), zero
  regressions.
- Full `tests/workers/`: 575 passed, zero failures.

## Stage 8 review: ACCEPT, two non-blocking findings flagged for follow-up

Independent review confirmed the "re-scored = regenerate via T6's
`generate_and_persist`" interpretation tracks the spec's own Dossier
lifecycle vocabulary directly — only `research_more_in_progress` is
tied to "new ResearchRun" (fresh evidence), `watching`'s "auto-rescore
loop" is not, so reusing the current `OpportunityScore` rather than
re-collecting evidence is correct, not a shortcut. It also confirmed
`next_recheck_at` advancement, the `ResearchRun`-skip reasoning, the
scheduler's `asyncio` correctness (no session leak, cancellation
propagates, no busy-loop risk), and the scope boundary. Two items
flagged as **non-blocking, not required before Stage 9**:

1. **Product question, not a T10 defect**: since nothing else in the
   codebase independently refreshes a creator's `OpportunityScore` on a
   schedule, a routine re-scan will often regenerate a dossier with
   identical content, yet unconditionally flips status back to
   `PENDING_REVIEW` — resurfacing it into human review every
   `recheck_days` regardless of whether the opportunity actually
   changed. Whether that's the desired behavior (vs. only resurfacing on
   a genuine score delta) is a product call for the user, not something
   this task's frozen scope can resolve.
2. **Pre-existing T6 bug, not introduced by T10**: `DossierGenerator.
   generate_and_persist`'s `_load_opportunity_scores` filters by
   `creator_id` only — `OpportunityScore`/`ProblemCluster` have no
   `niche_id` column — so it picks the creator's single globally
   top-scored opportunity across every niche, then stamps the *passed*
   `niche_id` onto the new `Dossier` row regardless. For a creator
   tracked across multiple watched niches, re-scanning niche A's dossier
   could persist niche B's top cluster mislabeled as niche A's. This
   predates T10 (T10 only calls the existing method) and would need a
   fix inside T6's own file, outside T10's frozen scope — flagged as a
   separate follow-up.

## Consequences

- Whichever later task wires application startup gets a fully tested
  `RegistryRescanScheduler(async_session, settings.scoring_rules_path)`
  to `start()`/`stop()` — no further design work needed there.
- The registry's re-scan cadence (`recheck_days`) now has exactly one
  source of truth (`rules/niche_discovery_prompt.yaml`), read by both
  T3's discovery engine and this scheduler.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF, none of which T10 touched — the same pre-existing
dev-environment changes disclosed in every ADR since T4. Not staged as
part of this task's commit.
