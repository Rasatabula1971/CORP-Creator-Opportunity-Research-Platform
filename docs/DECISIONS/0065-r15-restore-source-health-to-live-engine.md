# ADR-0065 — R15.11: restore the source-health circuit breaker onto the live discovery engine; delete the superseded one

**Status:** Stage 8: round 1 REVISE (two blocking — a fully-tripped breaker silently produced a `completed` run, and the temp filename was per-process rather than per-writer — both fixed with tests proven to fail without the fix; six non-blocking, all applied), round 2 ACCEPT (five non-blocking: the ADR's own test-count bookkeeping had gone self-contradictory and is corrected; the R12 blast radius and the transition-save are now stated consequences; the empty-tasks guard is self-describing; the concurrency test is acknowledged probabilistic as a standing guard, which is why both blocking fixes were also verified by reversion); Stage 9: pending
**Date:** 2026-09-22
**Reference:** `docs/REMEDIATION_PLAN_R15_acquisition.md` §0 and §2. This
task was not in the original R15 list — it emerged from asking what
`MultiSourceDiscovery` was actually for, and it supersedes §2's open
question ("wire it up, or delete it?").

## Context

`MultiSourceDiscovery` (`corp/workers/acquisition/multi_discovery.py`)
shipped 2026-09-15 as `d18359d`, *"Slice 26: Multi-source niche discovery +
source health tracking"*. Its module docstring names the motivation:

> "Sources that fail during the run have their failure recorded in the
> health tracker, but the run continues with remaining sources. This is the
> user's 'monitored, and after continued no response they are disconnected'
> feature."

Three days later, `1126ad9` (Stage 5, T3) introduced
`RecursiveNicheDiscovery`, which does strictly more — recursive drilling,
capability fan-out rather than platform fan-out, LLM synthesis, parallel
`asyncio.gather`, and the correct 3-part dedup key. T3 knew about the older
module (it cited it as prior art in its own docstring) but nothing was
deleted, and the API/CLI were pointed at the new engine.

**The circuit breaker went with the old module.** `SourceHealthTracker` had
exactly one consumer, and that consumer became unreachable: the API discover
job uses `RecursiveNicheDiscovery` (`jobs.py:326`), the CLI uses
`NicheDiscoveryCollector` (`run.py:130`), and neither touches health. No
`adapter_health.json` has ever been written — `corp_data/` holds only
`warm.db`. A user-requested feature had been silently absent for a week,
while its implementation kept being maintained by accident (R3 backfilled
provenance into it; it survived lint/mypy passes and a bugfix, `05b4b04`).

The verification that found this also found that the external review's
related items (health-state lost updates, non-atomic writes, acquisition
error taxonomy, and a genuine transaction-poisoning bug in
`multi_discovery._run_source`) were all **defects in code that never runs**.
Fixing dead code was the worst of the three options.

## Decision

**Restore the feature where it actually runs; delete the superseded engine.**

**`RecursiveNicheDiscovery` consults and updates the breaker.**
`_collect_evidence` now:
1. skips any platform where `is_available()` is false, logging the status
   and counting `stats.skip()` — so a disconnected source is no longer
   retried on every keyword of every drill;
2. records a failure when `build_adapter` raises;
3. records **one verdict per platform**, not per capability call. AppStore
   and Marketplace each expose two capabilities; a partial failure means the
   source *is* responding, so it counts as success. Only an all-capability
   failure records a failure, carrying the first exception;
4. persists via `save_async()` after the fan-out.

**Lifetime — the reason a naive port would not have worked.** The engine is
constructed fresh per job (`jobs.py:326`) and per watch re-scan
(`watch_rescan.py:429`). A per-engine tracker would reload from disk each
time and two live engines would last-writer-wins each other's counts, so
`consecutive_failures` could never reach `disconnect_after`. The tracker is
therefore a process-wide singleton (`get_shared_tracker`, an
`lru_cache(maxsize=1)` — the same precedent as the embedder at
`jobs.py:183-191`), injectable for tests. Single-process deployment is the
assumption, the same one `JobRegistry` already makes.

**Atomic persistence.** `save()` now writes a pid-suffixed temp file and
`os.replace`s it. This was listed in the R15 plan as deferred-because-dead;
it is live now. It matters more than "lost update": a crash mid-write left
truncated JSON, which `load()` swallows at `health.py:90-91` and silently
resets **every** source to healthy — the breaker would quietly disarm
itself. `save_async()` wraps it in `asyncio.to_thread`, matching the
codebase's existing use of `to_thread` for blocking work.

**Deleted:** `corp/workers/acquisition/multi_discovery.py` and
`tests/workers/test_multi_discovery.py`. The stale prior-art reference in
`niche_discovery.py`'s docstring is rewritten rather than left dangling.

**Test isolation.** An autouse `_isolated_source_health` fixture gives every
test its own tracker over `tmp_path`. Without it, any test exercising the
fan-out would read and write the developer's real
`corp_data/adapter_health.json` — polluting live operational state and
making the suite order-dependent, since a breaker tripped in one test would
skip sources in the next. `niche_discovery` imports the accessor by name, so
both the source module and the importing module are patched.

**Stage 8 revise round (applied).**
- *Blocking.* With every source circuit-broken, no task is created, so
  `stats.attempted == 0`, `resolve_status` returns `completed` and the run
  persists with no error — a total outage became indistinguishable from a
  quiet success, and the hourly R12 tick would repeat it silently. The
  superseded engine had this guard *and* a test for it
  (`test_all_sources_skipped_is_a_failed_run`); carrying the feature over
  without them was the defect. `_collect_evidence` now fails the run naming
  each passed-over source.
- *Blocking.* The temp file was named per **process**, but `save_async`
  hands the write to `asyncio.to_thread`, so two concurrent fan-outs in one
  process (a job and a re-scan tick) had two real threads writing the same
  temp path — truncating each other and publishing interleaved bytes, which
  `load()` swallows, silently resetting every source to healthy. Exactly the
  corruption the atomic write exists to prevent. Now `uuid4`-suffixed.
- `save()` gained `fsync` before the rename (the docstring claimed crash
  safety it did not have) and a `finally` that unlinks the temp file when
  `os.replace` fails, which on Windows happens whenever the destination is
  held open — otherwise one orphan accumulated per attempt, forever.
- `lru_cache(maxsize=1)` → `maxsize=None`. Keyed on a path, a size-1 cache
  evicts on every call if two paths ever alternate, silently handing each
  caller a freshly loaded tracker — the exact per-instance failure mode the
  singleton exists to prevent, with nothing failing loudly.
- Platform skips moved out of `stats.skip()` into
  `stats.extra["skipped_sources"]` with a per-source reason. Everywhere else
  in this engine `skip()` counts keywords/candidates; mixing units made the
  persisted `run.stats` unreadable, and the reasons are what an operator
  needs anyway.
- `save_async()` moved out of `_collect_evidence` (once per keyword, ~150
  writes per drill) to a `finally` in `discover()` and `research_more()` —
  once per run. Fewer writes, and far fewer windows to collide in.
- Test isolation rewritten to redirect `settings.corp_data_path` rather than
  patch the accessor in each importing module. The previous approach stopped
  protecting the developer's real `adapter_health.json` the moment a third
  importer appeared, and nothing would have failed to reveal it.

**Known gap, not closed here:** `SourceHealthTracker.summary()` now has no
consumer — nothing under `corp/api` exposes source health, so a disconnected
source is visible only in logs and in the failed run's message. Surfacing it
(an endpoint plus a console panel) is real work with a UI decision attached
and is logged as a follow-up rather than bolted on inside this task.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/adapters/health.py` | Atomic `save()`; `save_async()`; `get_shared_tracker()` singleton; docstring updated to name its real consumer |
| `corp/workers/intelligence/niche_discovery.py` | `health` parameter; skip unavailable platforms; per-platform verdicts; `stats.extra["skipped_sources"]` with a reason per source; the "no source available" guard that fails the run; `save_async()` once per run plus immediately on any status transition; adapters tracked as `(platform, adapter)`; stale docstring reference rewritten |
| `corp/workers/acquisition/multi_discovery.py` | **Deleted** (superseded by T3) |
| `tests/workers/test_multi_discovery.py` | **Deleted** with it |
| `tests/conftest.py` | Autouse `_isolated_source_health` fixture |
| `tests/integration/test_source_health_wiring.py` | New (8): disconnected source skipped and never built; repeated failures trip the breaker; partial capability failure counts as one success; state survives a new engine instance; **every source disconnected fails the run loudly and records per-source reasons**; **8 concurrent `save_async` calls never publish corrupt JSON**; temp file cleaned up when publish fails; `save()` is atomic and leaves no temp file |

No migration. No model changes.

## Verification

- `python -m ruff check` clean; `python -m mypy corp --strict` clean
  (138 files, down from 139 — one module deleted);
  `lint-imports` 3 contracts kept, 0 broken.
- `tests/integration/test_source_health_wiring.py`: 8 passed after round 2
  (5 at round 1).
- Full suite, no deselects, after round 2: **1333 passed, 1 skipped,
  0 failed** (round 1: 1330 / 0; baseline before this task: 1338 / 0).
- **Both blocking fixes were proven effective**, not assumed: each was
  temporarily reverted and the corresponding new test confirmed to fail
  (`test_every_source_disconnected_fails_the_run_loudly`,
  `test_concurrent_saves_never_publish_corrupt_json`), then restored and
  re-run green.
- `corp_data/` still contains only `warm.db` after the full suite — the
  isolation fixture demonstrably never touches real operational state.
- **Collected-count reconciled exactly** rather than assumed, by collecting
  the suite in a temporary worktree at `HEAD` and diffing test ids:
  **1339 collected before → 1334 now.** −12 (`test_multi_discovery.py`),
  −1 (`test_every_evidence_constructor_sets_type_and_origin` is
  parametrised per file containing an `Evidence(` constructor, so deleting
  the module correctly removed its case), +8 new.
  1339 − 13 + 8 = 1334 = 1333 passed + 1 skipped. ✓
  (At round 1 this read 1331 with 5 new tests; the round-2 tests changed it.)
- Not live-verified end to end: tripping a real breaker needs repeated real
  adapter failures. The tests drive the real engine against Postgres with
  faked adapters, covering skip, trip, partial-failure, cross-instance
  persistence, and atomic save.

## Consequences

- A source that stops responding is now degraded, then disconnected, then
  probed once per cooldown — instead of being hammered on every keyword of
  every drill, including the unattended hourly R12 watch re-scan.
- The breaker's counts survive the engine being rebuilt per job/tick, which
  is what makes `disconnect_after` reachable at all.
- ~700 lines of superseded acquisition code and its tests are gone, so
  future audits (and future accidental maintenance) no longer land on it.
- **Deliberate blast-radius expansion, stated rather than emergent** (Stage 8
  round 2): because `research_more()` can now legitimately return a `failed`
  run, and `watch_rescan.py:268` raises `RescanError` on a failed drill, a
  total source outage fails the *whole* R12 rescan for every watched dossier
  for the cooldown hour — skipping creator re-research, ideation and dossier
  generation, none of which depend on new niche evidence and all of which
  previously still ran when discovery came back empty. This is the intended
  trade (a silent no-op was the bug being fixed), but it is a real change in
  scope: "discovery yielded nothing" now escalates to "the watch system
  failed". If that proves too aggressive in practice, the narrower fix is for
  `WatchRescanner` to treat a drill that failed *only* for source-availability
  reasons as a skip rather than a stage failure.
- Health state is persisted on every status transition as well as once per
  run, so a crash or cancelled job mid-drill can no longer lose a whole
  run's accounting and leave a breaker permanently un-trippable across
  restarts.
- R15's §2 open question is closed. The remaining R15 items are unaffected;
  R15.1 (dual-capability adapters fetching twice) is in progress, and R15.2
  (the one-directional `is_busy` guard) follows.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root, as
in ADR-0061. Two pre-existing detached worktrees under `.claude/worktrees/`
are unrelated to this task.
