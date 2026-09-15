# Slice 15 — Campaign Research Batch

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

The final connection between the niche pipeline (Slices 7–14) and the
pre-existing per-creator `ResearchOrchestrator` (collect → intelligence →
cluster → intent → score → dossier → HUMAN_REVIEW): drive that orchestrator
across every creator onboarded under a campaign's SELECTED niches, in one
command, without a human having to look up and re-run `research
<creator_id>` for each one.

- `corp/workers/campaign_research.py` — `CampaignResearchBatch`: finds every
  distinct `Creator` reachable from the campaign's SELECTED CampaignNiche
  rows via `CreatorNiche` (Slice 4/14), skips creators that already
  progressed past `DISCOVERED` unless `--force`, and calls a
  `CreatorResearcher` (a narrow protocol — anything with an async
  `run(creator_id, *, skip_collect=False)`) for each eligible creator. One
  creator raising an exception is recorded and the batch continues — same
  resilience rule as every other multi-item pipeline in this codebase.

- `CreatorResearcher` is satisfied by the real `ResearchOrchestrator`
  unmodified (structural typing — no change to that class). Tests inject a
  `FakeResearcher` so selection/dedup/skip logic is verified without a real
  LLM provider or yt-dlp collector — the orchestrator itself already has no
  test coverage of its own (pre-dates these niche slices) and wiring a fake
  LLM for every internal stage was out of scope here.

- `RunType.CAMPAIGN_RESEARCH_BATCH` added to the enum in
  `corp/core/models/workflow.py`. No migration needed — `run_type` is
  stored as `String(30)`.

- CLI: `research-campaign <campaign_id> [--limit N] [--skip-collect] [--force]`.

Reuse, not rebuild: `ResearchOrchestrator` (pre-existing), `CreatorNiche`
(Slice 4), `CampaignNiche.SELECTED` (Slice 13), `start_run`/`finish_run`, no
migration needed.

## Acceptance criteria and how each is met

- **Every eligible onboarded creator gets researched.**
  `test_researches_eligible_creators` (2 DISCOVERED creators → 2 researched,
  2 succeeded).
- **Creators that already started research are skipped by default.**
  `test_skips_already_progressed_creators`.
- **`--force` re-researches already-progressed creators.**
  `test_force_reprocesses_already_progressed`.
- **Only SELECTED-niche creators are included, not merely VERIFIED.**
  `test_only_selected_niches_creators_included`.
- **A creator in multiple SELECTED niches is researched once.**
  `test_dedupes_creator_in_multiple_selected_niches`.
- **`--limit` caps the batch.**
  `test_respects_limit`.
- **One creator's failure doesn't sink the batch.**
  `test_handles_researcher_exception_gracefully` (1 errored, 1 succeeded,
  run still completes/partial, never crashes).
- **Empty campaign completes cleanly.**
  `test_empty_campaign`.
- **A creator whose pipeline stopped mid-way (not HUMAN_REVIEW) is counted
  as incomplete, not succeeded.**
  `test_incomplete_report_counted_separately`.
- **`--skip-collect` is passed through to the researcher.**
  `test_skip_collect_passed_through`.

## Verification

- `tests/integration/test_campaign_research_batch.py` (10, real Postgres):
  all selection/dedup/skip/force/limit/error paths against a `FakeResearcher`.
- Non-DB suite: 304 passed. DB suite: 10 passed. ruff: clean (pre-existing
  UP042 only).
- **Live** (dev DB, campaign "Slice 7 live demo", `--limit 1`, real
  `ResearchOrchestrator` — real yt-dlp collection + free-tier LLM calls via
  the FAIR router):
  - `research_run=dee14c1b... status=completed total=1 succeeded=1 incomplete=0 skipped=0 errored=0`
  - `succeeded: Lance Hedrick (1b6b8a56...) — human_review`
  - Every stage ran (collect, intelligence, clustering, intent, scoring,
    dossier) and the creator correctly reached `HUMAN_REVIEW`.
  - Collection returned 0 content items — yt-dlp's `/videos` tab lookup
    404'd for this particular channel ID. This is a pre-existing collector
    quirk (some channel IDs returned by a *search* aren't directly
    resolvable to a `/videos` listing URL the same way a canonical handle
    is) and out of scope for this slice — `AcquisitionCollector` and the
    YouTube adapter predate it. The batch's job was only to prove it drives
    every stage and reaches a terminal status without crashing even when an
    upstream stage yields nothing, which it did.

## Assumptions and open items

- `CreatorResearcher` is a *structural* protocol, not a formal ABC — chosen
  to avoid touching `ResearchOrchestrator` at all (it pre-dates the niche
  slices and has its own, separate scope). Any object with a matching `run`
  coroutine works, including future alternate researchers (e.g. a
  cheaper/faster smoke-test researcher).
- Eligibility is a single status check (`== DISCOVERED`), not a full state
  machine query — a creator stuck mid-pipeline (e.g. `COLLECTING`, if a
  previous run crashed uncommitted) is treated as "already progressed" and
  skipped, same as a fully completed one. `--force` is the escape hatch;
  a more granular retry policy is out of scope for this slice.
- No parallelism — creators are researched sequentially. Given the free-tier
  LLM rate limits this pipeline is built around, sequential is the safer
  default; a future slice could add bounded concurrency if throughput
  becomes the bottleneck.
