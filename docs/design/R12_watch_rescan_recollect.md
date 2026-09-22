# R12 — Watch re-scan re-collects evidence (and Research More completes)

**Stage:** 3 (product spec) + 4 (architecture) — **FROZEN 2026-09-22** (user accepted all five §6 recommendations as written: C for §3.3 with 0.05 / 10; §3.4 limits incl. `recollect_creator`; §4.2 Option A; Research More always resurfaces; order R12b → R12a → R12c → R12d)
**Origin:** ADR-0054 (R8) gate decision; `docs/REMEDIATION_PLAN_2026-09.md`
"Planned after this run".
**Spec basis:** CORP1 Product Spec & Build Plan — Watch: "parked.
Automatically re-scored on the same 90-day re-scan cycle as the registry,
so it can resurface on its own if the evidence strengthens." Registry:
"Re-scanning re-queries all evidence sources and updates the existing
registry entry." Research More: "automatically drills one level deeper
into the niche and re-queries all evidence sources for that specific niche,
then produces an updated dossier."

## 1. Problem (Stage 1/2 recap)

Today's Watch loop (T10 + R8) regenerates the dossier from whatever the
latest `OpportunityScore` already is. Nothing re-runs research for a watched
creator, so "the evidence strengthened" can only be true if some other job
happened to re-research that creator in the meantime — which nothing does.
Since R8, most re-scans will therefore correctly report `unchanged` and keep
the dossier `WATCHING`: honest, but the spec's promise ("resurface on its
own if the evidence strengthens") cannot trigger by itself.

A second, adjacent gap surfaced while reading the code for this design:
**Research More never finishes.** `POST /dossiers/{id}/decision` with
`research_more` sets the dossier to `research_more_in_progress` and runs
`RecursiveNicheDiscovery.research_more()` (niche drill at depth+1) in the
background — and stops. The spec's "then produces an updated dossier" never
happens; nothing regenerates the dossier or leaves the
`research_more_in_progress` state. Grep: that status is written in one
place and read nowhere.

Both are the same missing capability: **"re-research this creator/niche and
produce a new dossier version, then decide whether it changed."**

## 2. What exists to build on (Stage 2 research, verified in code)

| Piece | Where | Notes |
| --- | --- | --- |
| Creator research chain | `corp/workers/orchestrator.py::ResearchOrchestrator.run(creator_id, skip_collect)` | collect → intelligence → cluster → intent → scoring → HTML dossier → `HUMAN_REVIEW`. Does **not** run the competitive pipeline or product ideation, and does not call `generate_and_persist`. Moves the creator through the state machine; each stage is its own committed `ResearchRun`. |
| Niche re-query | `niche_discovery.py::research_more(niche_id, campaign_id)` | Drills the niche at parent depth+1 across all NICHE-family adapters (R5: incl. crowdfunding, patreon_substack); respects `max_depth` (R5); tags its run with `niche_id`, so R6's dossier scoping sees its evidence. |
| Persisted dossier | `DossierGenerator.generate_and_persist(creator_id, niche_id)` | Supersedes the prior active dossier, writes a new `PENDING_REVIEW` row (T6). |
| Scheduler | `scheduler/registry_rescan.py` | Hourly in-process loop; `find_due_watched_dossiers`; per-dossier savepoint, clock on success, `content_fingerprint` unchanged→`WATCHING` (R8). Wired at app startup (ADR-0045). |
| Jobs | `corp/api/jobs.py::JobRegistry` | `execute()` never raises; `active_for_campaign()` prevents two campaign jobs at once; `run_research(creator_id, skip_collect)` is the API's creator-research entry. |
| Creator state machine | `corp/core/state/machine.py` | `WATCHING → COLLECTING` **is** allowed (a watched creator may be re-researched); `HUMAN_REVIEW → COLLECTING` is **not**. |
| Dossier gate vs creator status | `routes_ops.py:591-605` | Watch sets `Dossier.status = WATCHING` only; the **creator** stays `HUMAN_REVIEW`. So today a dossier-gate Watch leaves the creator in a state from which `ResearchOrchestrator` cannot restart (first stage `advance(COLLECTING)` would raise `InvalidTransitionError`). |
| LLM cost controls | `corp/config.py` | Provider pool with per-provider daily-cap cooldown (`llm_cooldown_seconds`) and fail-over; no per-job or per-tick budget exists. YouTube Data API has a daily quota setting. |

## 3. Product specification (Stage 3 — to freeze)

### 3.1 Watch re-scan (R12)

When a `WATCHING` dossier's niche passes `next_recheck_at`, CORP1 shall:

1. **Re-query the niche's evidence sources** — run `research_more` for the
   dossier's niche (depth+1 drill, all NICHE adapters). This satisfies
   "re-scanning re-queries all evidence sources" for the niche side and
   updates the registry entry (clock stamped on completion, R5/R8).
2. **Re-research the creator** — run the creator chain with fresh
   collection (`skip_collect=False`): collect → extract → cluster → intent
   → score, producing a new active `OpportunityScore` set.
3. **Regenerate product ideas and the persisted dossier** for
   (creator, niche) — `generate_and_persist`, which supersedes the watched
   dossier (append-only history preserved).
4. **Decide whether the evidence strengthened** (§3.3) and set the new
   dossier's status: `PENDING_REVIEW` (resurfaced) or `WATCHING` (still
   parked).
5. Record one `ResearchRun` of a new `run_type = watch_rescan` per dossier,
   parented to the individual stage runs via `config_snapshot`, so the
   dossier's history explains *why* it resurfaced.

### 3.2 Research More completion (R12a — same machinery, do first)

After `research_more()` finishes for a dossier's niche, CORP1 shall run
steps 2–3 above for that dossier's creator/niche and set the new dossier to
`PENDING_REVIEW` unconditionally (the human asked for more research; they
expect to see the result). The `research_more_in_progress` state is then
left behind by supersession. On failure at any stage the dossier returns
to `PENDING_REVIEW` with the failure visible in the run, never stuck.

### 3.3 "The evidence strengthened" — definition (decision needed)

Options, from cheapest to most faithful:

- **A. Score delta.** Resurface iff the new top opportunity's
  `aggregate_score` ≥ old + `watch_resurface_min_delta` (proposed 0.05) **or**
  its confidence band improved (e.g. `low → medium`). Deterministic, uses
  the existing scoring engine, cheap to explain in the dossier ("+0.08,
  medium → high").
- **B. Evidence delta.** Resurface iff new *distinct* evidence rows linked
  to the niche/creator since the watched dossier ≥ N (proposed 10) **and**
  score did not fall. Captures "more people are saying this" even when the
  score is flat.
- **C. Either A or B.** Recommended: A covers strength, B covers volume;
  both are stated in the dossier's recommendation block.

`content_fingerprint` (R8) stays as the last-resort guard: identical content
never resurfaces regardless of A/B.

### 3.4 Cost and safety limits (decision needed)

A full re-research per watched dossier costs LLM calls (extraction, intent,
synthesis) and adapter calls. Proposed, all configurable in
`rules/niche_discovery_prompt.yaml` (same file `recheck_days` lives in):

- `watch_rescan.max_dossiers_per_tick`: **3** (hourly tick → ≤72/day).
- `watch_rescan.skip_when_provider_cooling`: **true** — if the LLM pool has
  every provider in cooldown, defer the tick (`next_recheck_at` untouched,
  R8's "retry tomorrow" applies).
- `watch_rescan.recollect_creator`: **true** — set `false` to fall back to
  today's behaviour (re-render only) for a cheap dry run.
- One job per campaign at a time is already enforced by `JobRegistry`;
  the scheduler must respect it (skip a dossier whose campaign has an
  active job; it stays due).

### 3.5 Human-visible behaviour

- Dashboard: a resurfaced dossier appears in the review queue with a
  "Resurfaced from Watch — reason: score +0.08 / 14 new evidence rows"
  line in the recommendation block; a still-parked one keeps `WATCHING`
  with "re-scanned <date>, unchanged".
- Re-scan page (`/rescan`): shows last re-scan outcome per watched dossier
  (`resurfaced` / `unchanged` / `failed`).
- Nothing changes at the decision gates themselves.

### 3.6 Non-goals

- Re-scanning **rejected** dossiers (spec: "not re-suggested outside normal
  re-scan timing" — the niche registry handles that; the dossier stays
  rejected).
- The weak-niche "revisit later" state (3–6 months OR renewed trend
  signal). Its trigger ("renewed interest") reuses §3.3-B's evidence-delta
  once R12 exists; design it as R13 after R12 ships.
- New adapters.

### 3.7 Acceptance tests (Stage 3, frozen with the spec)

1. A `WATCHING` dossier whose niche is due, with a fake adapter now
   returning stronger evidence, ends the tick as a new `PENDING_REVIEW`
   dossier whose content says why; the old row is superseded.
2. Same, but adapters return the same evidence: new row is `WATCHING`,
   `RescanStats.unchanged` incremented, clock advanced.
3. Any stage failure: old dossier untouched (still `WATCHING`), clock moves
   by `retry_days` only, a `watch_rescan` run is `failed`, batch continues.
4. `research_more` decision on a `PENDING_REVIEW` dossier ends with a new
   `PENDING_REVIEW` dossier version; no dossier remains
   `research_more_in_progress` after the job completes.
5. `max_dossiers_per_tick` = 1 with two due dossiers: exactly one is
   processed; the other is still due on the next tick.
6. A creator whose status is `HUMAN_REVIEW` at Watch time can be
   re-researched (see §4.2) — no `InvalidTransitionError`.
7. Evidence appended by the re-scan carries `evidence_type` and `origin`
   (R3's DB constraint makes this automatic; assert anyway).

## 4. Architecture (Stage 4 — options, recommendation)

### 4.1 Where the chain lives

- **Option 1 — a new worker, `corp/workers/watch_rescan.py`,**
  `WatchRescanner.rescan(dossier_id)` that composes the existing pieces:
  `research_more` → `ResearchOrchestrator.run(skip_collect=False)` →
  `ProductIdeationGenerator` → `generate_and_persist` → §3.3 decision. The
  scheduler calls it per due dossier inside R8's savepoint. Research More
  completion (§3.2) calls the same worker with `always_resurface=True`.
  **Recommended:** one place for "re-research and re-dossier", reused by
  both triggers; the scheduler and the decision route stay thin.
- Option 2 — extend `rescan_watched_dossiers` in place. Rejected: it would
  make the scheduler own pipeline orchestration and duplicate what
  `_run_research_more` needs.

### 4.2 The creator state problem

`ResearchOrchestrator` starts with `advance(COLLECTING)`, legal only from
`DISCOVERED`/`WATCHING`. A dossier-gate Watch leaves the creator at
`HUMAN_REVIEW`. Options:

- **A. Dossier-gate Watch also moves the creator to `WATCHING`** (and
  Approve/Reject likewise mirror to `APPROVED`/`REJECTED`), via the state
  machine, so the creator's status agrees with its active dossier. Then
  `WATCHING → COLLECTING` is already legal. **Recommended** — it is what
  the two-gate design intended (`Dossier.status` is documented as a
  denormalised mirror), and it removes the current inconsistency where a
  creator shows `human_review` under a watched dossier. Requires a small
  backfill for existing rows and a decision on multi-niche creators
  (creator = `WATCHING` iff *no* active dossier is `PENDING_REVIEW`).
- B. Add `HUMAN_REVIEW → COLLECTING` to the machine. Simpler, but lets a
  creator be re-researched *while* a human is reviewing its dossier.
  Rejected.
- C. Give the orchestrator a `resume_from=SCORED`-style bypass. Rejected:
  hides state from the machine that exists precisely to make it visible.

### 4.3 Data model

No new tables. Additions:

- `RunType.WATCH_RESCAN` (and reuse `NICHE_DISCOVERY` for the drill,
  `CREATOR_RESEARCH` for the stages).
- `Dossier.content["rescan"]`: `{trigger: "watch"|"research_more",
  previous_dossier_id, score_delta, new_evidence_count, resurfaced: bool,
  reason: str}` — written by the worker, rendered by R7's panel. No column
  needed; it is dossier content.
- Rules file keys from §3.4.

Migration: enum value only (`ALTER TYPE runtype ADD VALUE 'WATCH_RESCAN'`)
if `run_type` is a PG enum — verify; the model stores it as `String` today
(`ResearchRun.run_type` default `"creator_research"`), so likely none.

### 4.4 Concurrency and cost

- The scheduler tick is sequential; each dossier is one savepoint (R8).
  A re-research can take minutes; the hourly interval is fine, but the tick
  must not overlap itself — `_run_forever` already awaits each tick.
- Respect `JobRegistry.active_for_campaign`: skip and leave due.
- `max_dossiers_per_tick` bounds LLM spend; provider cooldown check
  (§3.4) avoids burning a tick into a failing pool.

### 4.5 Failure semantics

Inherit R8: savepoint per dossier; on failure the old dossier stays
`WATCHING`, `next_recheck_at = now + retry_days`; the `watch_rescan` run is
`failed` with the stage that failed named in `error_message`. For Research
More: the dossier is returned to `PENDING_REVIEW` (never stuck).

### 4.6 Notes carried from R12b's Stage 8 review (2026-09-22)

- `registry_rescan.py` and `generate_and_persist` create `PENDING_REVIEW`
  rows without mirroring the creator. After R12b that opens a window: a
  watched creator whose re-scan resurfaces stays `WATCHING` while a dossier
  awaits review, and the "unchanged → WATCHING" branch could leave a creator
  at `HUMAN_REVIEW` after the orchestrator advanced it. **R12a/R12c must
  call `mirror_creator_status` after the §3.3 decision** (and after the
  Research More regeneration).
- Found during R12a preparation: `ProductIdeationGenerator` (T5) has no
  caller in `corp/` — product ideas are never generated in production, so
  every real dossier's Product Concepts section is empty. R12a's chain
  includes ideation; the same task should also run ideation in the normal
  `POST /creators/{id}/dossier/generate` path (LLM cost accepted: it is
  the spec's step 6).

## 5. Task decomposition (Stage 5 — proposed)

| Task | Scope | Depends on |
| --- | --- | --- |
| **R12a** Research More completes | `WatchRescanner` core (`research_more` → orchestrator → ideation → `generate_and_persist`), called from `_run_research_more`; dossier never stuck; tests §3.7-4,6,7 | §4.2 decision |
| **R12b** Creator status mirrors dossier gate | Dossier gate Watch/Approve/Reject move the creator via the state machine; backfill; tests | — (can precede R12a) |
| **R12c** Watch re-scan uses the rescanner | Scheduler calls `WatchRescanner` with §3.3 decision, §3.4 limits, `content["rescan"]`; tests §3.7-1,2,3,5 | R12a, R12b |
| **R12d** Surface it | R7 panel shows the rescan block; `/rescan` page shows last outcome | R12c |

Estimated: R12b small; R12a medium; R12c medium; R12d small.

## 6. Decisions needed to freeze

1. §3.3 — strengthened = **C (score delta OR evidence delta)**? Threshold
   values (0.05 / 10 rows)?
2. §3.4 — `max_dossiers_per_tick = 3`, provider-cooldown skip, and the
   `recollect_creator` kill-switch?
3. §4.2 — **Option A** (dossier gate mirrors to creator status)?
4. §3.2 — Research More always resurfaces to `PENDING_REVIEW` (no
   strengthened check)?
5. Order: R12b → R12a → R12c → R12d?
