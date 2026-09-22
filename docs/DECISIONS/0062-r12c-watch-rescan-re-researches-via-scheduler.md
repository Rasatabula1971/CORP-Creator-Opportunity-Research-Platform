# ADR-0062 — R12c: the Watch re-scan scheduler re-researches through the WatchRescanner under per-tick limits

**Status:** Stage 8: round 1 REVISE (one blocking — session rollback inside the rescanner expired the loop's `Dossier` rows — fixed with a reproducing test; five non-blocking, all applied), round 2 ACCEPT (three non-blocking, applied: the rescanner rolls a poisoned session back before recording the failed run — with test; the post-`generate_and_persist` failure consequence stated here and corrected in ADR-0061; wording brought in line with the code); Stage 9: accepted by user 2026-09-22
**Date:** 2026-09-22
**Reference:** `docs/design/R12_watch_rescan_recollect.md` (frozen) §3.1,
§3.3, §3.4, §3.7-1,2,3,5,7; task R12c. Spec: "Watch — parked so it can
resurface on its own if the evidence strengthens." ADR-0061 (R12a) built
the rescanner; this ADR points the hourly scheduler at it.

## Context

Since R8 (ADR-0054) the `RegistryRescanScheduler` regenerated a due
`WATCHING` dossier from *existing* data only: it re-rendered and compared
fingerprints. No new evidence was ever collected, so "if the evidence
strengthens" could not happen without a human clicking Research More.
R12a produced `WatchRescanner.rescan(dossier_id, trigger="watch")`, which
re-queries the niche, re-runs the creator chain, regenerates ideas and the
dossier, and applies the frozen resurface rule (§3.3 C). R12c wires it in.

## Decision

**`rescan_watched_dossiers(...)` gains an optional re-research path.**
With `rescanner=` it calls `rescan(dossier.id, trigger="watch")` per due
dossier; `resurfaced`/`unchanged` come from `outcome.decision.resurfaced`
(the rescanner already sets the new version's status and writes
`content["rescan"]`). Without one, the pre-R12c re-render path runs
byte-for-byte unchanged inside its savepoint — the fallback when no LLM
provider is configured.

**Transaction shape differs by path, on purpose.** The creator chain
commits between orchestrator stages, so the re-research path cannot run
inside a SAVEPOINT (a commit would end it). Instead the scheduler commits
after each dossier's success (clock advance included) and after each
failure's retry bookkeeping; a dossier failing mid-chain relies on the
rescanner's own contract (ADR-0061: the old dossier is never left dead, the
`watch_rescan` run is failed). A failure while recording the retry rolls
the session back so the batch continues.

**Limits (design §3.4, config `watch_rescan:` in
`rules/niche_discovery_prompt.yaml`).**
- `max_dossiers_per_tick` (3): due dossiers beyond the cap are counted
  `deferred` and stay due; `find_due_watched_dossiers` now orders
  `next_recheck_at asc, generated_at asc` so the longest-overdue go first.
- Busy job: `is_busy(campaign_id | None, creator_id)` (app wiring
  `_job_busy`: `JobRegistry.active_for(creator_id)` then
  `active_for_campaign`, the campaign being the dossier's most recent
  `CampaignNiche` association) — a busy one is deferred, not failed, and
  its clock is untouched. Only consulted on the re-research path, as is
  the cap.
- Provider cooling: the `rescanner_factory` raises `RescanDeferredError`
  when the pool's `available()` is empty and
  `skip_when_provider_cooling` is on; the tick logs and returns having
  touched nothing, and it does **not** count as a scheduler failure (no
  back-off). Only the pooled configuration exposes `available()`;
  `FairProvider` and a bare single-key provider do their own quota
  handling and are never deferred. `recollect_creator: false` in config
  disables the factory entirely (re-render only).

**Scheduler wiring.** `RegistryRescanScheduler(..., rescanner_factory=,
is_busy=)`. Each tick: call `rescanner_factory(session, cfg)` for a
`RescannerHandle` (rescanner + `aclose`), run the pass, close the handle
in `finally`, log the mode (`re-research` / `re-render`).
`corp/api/app.py` provides `RescanProviders` — one LLM provider for the
scheduler's lifetime (see the revise round), `factory` returning `None` on
`ProviderConfigError` — and `_job_busy`.

**Failure after `generate_and_persist`.** Because this path commits per
dossier, a non-DB failure in the decision/mirror steps durably leaves the
old dossier superseded and the new one `PENDING_REVIEW` without a `rescan`
block, with the niche retried in `retry_days` — one active dossier,
surfaced to a human; accepted (ADR-0061 said a savepoint would revert it;
corrected there).

`RescanStats` gains `resurfaced` and `deferred`.

**Stage 8 revise round (applied).**
- *Blocking.* The rescanner shares the tick's session and the orchestrator
  rolls it back on a DB error (ADR-0061 round 2), which expires every loaded
  row — so `dossier.id` in the `except` handler raised `MissingGreenlet`,
  escaping the batch: no retry clock, remaining dossiers unprocessed, the
  `watch_rescan` run left `running`, and the tick counted as a scheduler
  failure (five identical ticks would halt the loop). Fix: the loop works
  from `(dossier_id, niche_id, creator_id)` captured before any rescan;
  the failure branch first commits (keeping the rescanner's own failed-run
  bookkeeping) or rolls back if the session is unusable, then records the
  retry clock in a fresh transaction.
  `test_rescanner_rollback_still_retries_and_batch_continues` reproduces
  the commit-then-FK-violation-then-rollback path.
- The "every provider cooling" deferral was dead code: a fresh
  `PooledProvider` per tick starts with an empty cooldown table. The
  provider now lives for the scheduler's lifetime (`RescanProviders` in
  `app.py`, closed at shutdown; the tick handle's `aclose` is a no-op), so
  cooldown state carries between ticks; `skip_when_provider_cooling` is
  honoured (the factory receives the scheduler's `WatchRescanConfig`);
  "unconfigured" is remembered so the warning logs once, not hourly.
- The per-tick cap and busy check apply only on the re-research path; the
  cheap re-render fallback clears any backlog in one tick (T10's 24-hour
  invariant is kept).
- Busy check is `is_busy(campaign_id | None, creator_id)`: a console job
  already researching the creator (`JobRegistry.active_for`) defers the
  dossier too — the rescanner's precondition only catches it once the job
  has moved the creator out of `WATCHING`.
- A failing `build_watch_rescanner` closes the provider instead of leaking
  its HTTP client; a failing `handle.aclose()` is logged, not counted as a
  tick failure.

**Design §3.7-7 (re-scan evidence carries provenance)** now has its
explicit test: a fake driller that persists `Evidence` rows under the
drill run; they carry `evidence_type`/`origin` and are counted by
`count_new_evidence` through the niche-tagged run.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/scheduler/registry_rescan.py` | `RescannerHandle`, `RescannerFactory`, `RescanDeferredError`, `BusyCheck`; `RescanStats.resurfaced/deferred`; ordering in `find_due_watched_dossiers`; `_campaign_for_niche`; re-research path + cap + busy skip in `rescan_watched_dossiers`; scheduler `__init__`/`_tick` |
| `corp/api/app.py` | `RescanProviders` (lifetime provider, factory, `aclose`), `_job_busy`; wired into the scheduler and closed in lifespan |
| `tests/integration/test_registry_rescan.py` | `FakeRescanner`, `RollbackRescanner`; 10 tests: resurfaces + clock; unchanged stays WATCHING; per-tick cap defers longest-overdue-last; busy campaign skipped and stays due; busy creator skipped without a campaign; failure retries in `retry_days` and batch continues; rollback inside the rescanner still retries and continues; cap does not apply to the re-render fallback; scheduler tick defers on `RescanDeferredError` (nothing touched, no failure count); scheduler tick hands its config to the factory, uses the rescanner and closes the handle |
| `corp/workers/watch_rescan.py` | Round 2: rolls a poisoned session back before recording the failed run |
| `docs/DECISIONS/0061-…md` | Round 2: savepoint sentence corrected |
| `tests/integration/test_watch_rescanner.py` | `EvidenceAddingDriller`; provenance + new-evidence-count test (§3.7-7); `PoisoningIdeator`; DB error in a post-orchestrator stage still fails the run and restores the dossier |
| `tests/api/test_lifespan.py` | Scheduler construction assertion includes the two new kwargs; 3 `RescanProviders` tests (one provider across ticks, defer when cooling, flag off, closed at shutdown; closed when rescanner build fails; unconfigured remembered) |

No migration. No model columns. No new config keys (all from R12a's block).

## Verification

- `python -m ruff check` clean; `python -m mypy corp --strict` clean (139 files).
- `tests/integration/test_registry_rescan.py` +
  `tests/integration/test_watch_rescanner.py` + `tests/api/test_lifespan.py`:
  46 passed (15 new) after round 2 (39 / 8 at round 1; 45 / 14 after it).
  The round-2 test was confirmed to fail with the rescanner fix removed.
- Full suite, no deselects, after round 2: **1326 passed, 1 skipped,
  0 failed** (round 1: 1319 / 0; after round-1 fixes: 1325 / 0).
- Not live-verified: a real tick needs an LLM provider and adapters. The
  integration tests drive the real scheduler `_tick` against Postgres with
  a fake rescanner and a fake factory; the app factory is exercised only by
  the lifespan tests (mocked scheduler).

## Consequences

- A watched dossier is now automatically re-researched — new niche
  evidence, re-scored creator, fresh ideas — and resurfaces only when the
  §3.3 rule says the evidence strengthened; unchanged versions stay parked.
- Cost is bounded per tick by the cap, and a tick never competes with a
  running campaign job on the same campaign or with a cooling provider.
- The re-render fallback remains for deployments without a provider, so
  R8's behaviour is preserved rather than replaced.
- R12d only has to display `content["rescan"]` and the last tick's outcome.
