# ADR-0061 — R12a: Research More completes through a shared WatchRescanner; product ideation wired

**Status:** Stage 8: round 1 REVISE (non-blocking, applied), round 2 REVISE (one blocking — run id expired after rollback — fixed with a reproducing test), round 3 ACCEPT (its one observation applied: the failure restore also re-mirrors the creator so it is un-parked with the dossier); Stage 9: accepted by user 2026-09-22
**Date:** 2026-09-22
**Reference:** `docs/design/R12_watch_rescan_recollect.md` (frozen) §3.2,
§4.1 Option 1, §4.3, §4.5, §4.6; task R12a. Spec: "Research More — CORP1
automatically drills one level deeper into the niche and re-queries all
evidence sources for that specific niche, then produces an updated dossier."

## Context

A `research_more` decision set the dossier to `research_more_in_progress`
and ran the niche drill in the background — and stopped. No creator
re-research, no new dossier, no way out of that status (written in one
place, read nowhere). Separately, T5's `ProductIdeationGenerator` had no
caller in `corp/` since it shipped "tested, unwired", so every real dossier
was produced with an empty Product Concepts section (design §4.6).

## Decision

**`corp/workers/watch_rescan.py` — `WatchRescanner`.** One worker for both
re-research triggers (Research More now; the Watch re-scan in R12c):

1. niche re-query — `research_more(niche_id, campaign_id)` (skipped, with
   a note in the run, when the niche has no campaign association);
2. creator re-research — the orchestrator chain with fresh collection. It
   restarts only from `WATCHING`; a creator still at `HUMAN_REVIEW`
   (Research More) is first parked there via `advance(strict=True)` — a
   legal move and an honest state: it is not reviewable while being
   re-researched (design §4.2 left this to R12a);
3. product ideation;
4. a new persisted dossier version (`generate_and_persist`, supersedes);
5. the resurface decision (`decide_resurface`, pure; design §3.3 C):
   `always` for Research More; else identical content never resurfaces;
   else score delta ≥ 0.05 OR band improved OR ≥ 10 new evidence rows with
   the score not falling. Result written to `content["rescan"]`
   (`trigger, previous_dossier_id, resurfaced, reason, score_delta,
   new_evidence_count, run_id, at`); a non-resurfaced version stays
   `WATCHING`;
6. `mirror_creator_status` (R12b), closing the gap noted in design §4.6.

Collaborators are injected behind three small protocols (`NicheDriller`,
`CreatorResearcher`, `Ideator`); `build_watch_rescanner()` wires
`RecursiveNicheDiscovery`, `ResearchOrchestrator`, `ProductIdeationGenerator`.
One `ResearchRun` of the new `RunType.WATCH_RESCAN` per rescan carries the
stage run ids and the decision in `stats.extra`. Thresholds and the
`recollect_creator` switch live in `rules/niche_discovery_prompt.yaml`
(`watch_rescan:` block) via `WatchRescanConfig.from_rules`.

**Failure semantics.** The old dossier is never left dead: any stage
failure raises `RescanError("<stage>: …")`, the `watch_rescan` run is
failed with that message, and a `research_more_in_progress` dossier is put
back to `PENDING_REVIEW`. A failed `research_more` drill or a failed
orchestrator stage (any run with `status == "failed"`) counts as failure.

**Stage 8 revise round (applied).**
- The orchestrator commits between stages and can roll the shared session
  back on a DB error, which expires every loaded attribute — **including
  the run's primary key** (round 2 proved `run.id` itself raises after
  such a rollback). The run id is captured right after `start_run`; the
  failure bookkeeping re-fetches the run by that id and is wrapped so it
  can never mask the original exception.
- `_run_research_more`: after any failure the `PENDING_REVIEW` restore is
  re-checked in a fresh transaction **unconditionally** (status-guarded,
  so a second restore is a no-op) — a rolled-back session commits cleanly
  having lost the restore, the route committed
  `research_more_in_progress` before the job started, and "never stuck"
  (design §3.2) is the contract. `test_rollback_in_researcher_still_fails_run_and_restores_dossier`
  reproduces the commit-then-rollback path.
- Precondition: with `recollect_creator`, the creator must be `WATCHING`,
  `HUMAN_REVIEW` or `DISCOVERED`; anything else (an `APPROVED` multi-niche
  creator, one mid-pipeline) is refused with `RescanError("precondition:
  …")` rather than letting the orchestrator's non-strict stage moves skip
  silently and re-supersede every score while reporting success.
- Best-effort ideation in `POST …/dossier/generate` now catches any
  exception (logged), not only "provider not configured", and a failing
  `provider.close()` is logged rather than 500-ing the route — ideas are
  additive; the dossier must still ship.
- Documented, not changed: a failure after `generate_and_persist` (steps
  5–6) leaves the old dossier superseded and the new one `PENDING_REVIEW`
  without a `rescan` block — no double-active dossier, and R12c's
  per-dossier savepoint reverts the whole rescan in the scheduler path;
  `content_fingerprint` is practically never equal once ideation runs
  (`product_ideas[].id` differs per run), so it stays a last-resort guard;
  design §3.7-7 (re-scan evidence carries provenance) is covered only by
  R3's `NOT NULL` here and gets an explicit fake-adapter test in R12c.

**Route.** `_run_research_more(dossier_id, niche_id, campaign_id)` now
builds the rescanner and calls `rescan(trigger="research_more")`; the
route passes `dossier.id` into the background task.

**Product ideation in the normal path.** `POST /creators/{id}/dossier/generate`
runs `ProductIdeationGenerator` before persisting — best-effort: with no LLM
provider configured it logs and skips (the dossier is still produced, ideas
empty) rather than turning dossier generation into a 503. This is the LLM
cost the user accepted at the R12b gate.

`content_fingerprint` moved from `registry_rescan.py` to `watch_rescan.py`
(re-exported) so the scheduler can import the rescanner in R12c without a
cycle; it now also ignores the `rescan` block.

`DossierGenerator.count_new_evidence(creator_id, niche_ids, since)` is the
public "new distinct evidence rows since" query, same scope as demand
validation.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/watch_rescan.py` | New: config, protocols, `decide_resurface`, `WatchRescanner`, `build_watch_rescanner`, `content_fingerprint` |
| `corp/workers/scheduler/registry_rescan.py` | Imports `content_fingerprint` from the new module |
| `corp/workers/dossier/generator.py` | `count_new_evidence` |
| `corp/core/models/workflow.py` | `RunType.WATCH_RESCAN` (String column; no migration) |
| `rules/niche_discovery_prompt.yaml` | `watch_rescan:` block |
| `corp/api/routes_ops.py` | `_run_research_more` via the rescanner; `settings` import |
| `corp/api/routes.py` | Best-effort ideation before persisting a dossier; `logger` |
| `tests/integration/test_watch_rescanner.py` | New: 6 pure decision tests + 10 chain tests (resurface on score — persisted state re-read via `refresh`; unchanged stays WATCHING; resurface on evidence volume; Research More always resurfaces and parks the creator; failed stage restores PENDING_REVIEW and names the stage; failed drill leaves the watched dossier active; no-campaign skips the drill; `recollect_creator=False` re-renders only; an APPROVED creator is refused; a researcher that commits then rolls back still fails the run and restores the dossier) |
| `tests/api/test_dossier_decision_endpoint.py` | Fake `_run_research_more` takes `dossier_id` |

No migration. No model columns.

## Verification

- `python -m ruff check` clean; `python -m mypy corp --strict` clean.
- `tests/integration/test_watch_rescanner.py` +
  `tests/api/test_dossier_decision_endpoint.py` +
  `tests/integration/test_registry_rescan.py` + `tests/api/test_endpoints.py`:
  65 passed (16 new) after round 2.
- Full suite, no deselects, after round 2: **1311 passed, 1 skipped,
  0 failed** (round 1: 1309 / 0; after round-1 fixes: 1310 / 0).
- Not live-verified end to end: the real chain needs an LLM provider and
  adapters; the integration tests fake those three collaborators and run
  everything else (supersession, decision, run bookkeeping, mirror,
  failure restore) against Postgres. The seeded dev creator now has the
  ideation step available through Generate Dossier when a provider is
  configured.

## Consequences

- A Research More decision now ends with a new `PENDING_REVIEW` dossier
  version that carries fresh niche evidence, re-scored opportunities,
  product ideas, and a `rescan` block explaining its origin; the
  `research_more_in_progress` state is transient by construction.
- R12c only has to call `rescan(dossier_id, trigger="watch")` from the
  scheduler under the per-tick limits.
- Real dossiers gain product ideas whenever an LLM provider is configured.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
