# Slice 5 — Generalize ResearchRun

**Status:** ACCEPTED
**Date:** 2026-09-14
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, Slice 5 / §11 / ADR-003

## What shipped

`ResearchRun` gains `run_type` (NICHE_DISCOVERY / NICHE_VERIFICATION /
CREATOR_RESEARCH, default CREATOR_RESEARCH), plus optional `campaign_id` and
`niche_id` foreign keys. `creator_id` was already nullable. A new validator
(`corp.core.state.research_run.validate_run_type`) enforces §11's full rule set for
call sites that opt in.

`run_type` is a new column alongside the pre-existing `scope` column, not a
replacement for it. They are different axes: `scope` describes the breadth of an
existing creator-pipeline run (one creator vs cross-creator), `run_type` describes
what kind of research the run is. Neither was collapsed into the other.

## Architecture tension found and how it was resolved

§11 states "CREATOR_RESEARCH requires creator_id". But `ClusterPipeline.run()` takes
`creator_id: str | None = None`, and `start_run()` in `corp/workers/intelligence/runs.py`
explicitly maps `creator_id=None` to `RunScope.CROSS` — cross-creator clustering is
existing, designed creator-pipeline behavior (PDR #3 in IMPLEMENTATION_STEPS.md),
even though no production rows currently exercise it (checked: 2 rows, both
single-creator).

Enforcing the doc's rule as a hard DB constraint would break that capability. And
"creator collector redesign" is explicitly out of scope for this slice, so
retrofitting the existing call sites to pass an appropriate run_type was not an
option either.

**Resolution:** the database enforces only the unambiguous half of the rule —
`NICHE_VERIFICATION` requires `niche_id` (a CHECK constraint). `CREATOR_RESEARCH` is
deliberately not constrained to require `creator_id` at the DB level. The full rule
set lives in `validate_run_type()` for new call sites (niche discovery/verification,
later slices) to call before creating a run. A dedicated test,
`test_cross_creator_research_run_still_allowed`, pins the existing capability so a
future slice cannot silently break it.

This is the reading most consistent with the doc's own priorities: "existing
creator-run behavior must remain valid" (Slice 5 acceptance criterion) and "preserve
existing interfaces unless explicitly authorized" (Standard Coding Contract) outrank
a literal application of one validation bullet.

## Problems found during this slice

None in the shipped code. One process mistake: a `git stash` I used mid-task to
verify the mypy/ruff baseline reverted my three in-progress edits when popped. Caught
immediately, redone identically, reverified. The final state is correct; recording it
because it is exactly the kind of slip the per-slice review loop exists to catch.

## Unresolved, pre-existing issues

Unchanged from Slices 1–4: `tests/integration/test_migration.py` and
`tests/api/test_endpoints.py` remain broken due to hardcoded assumptions from a
different machine. Not touched.
