# Slice 13 — Niche Selection

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

The final step of the niche pipeline: rank VERIFIED, qualified niches by
`qualification_score` and move each to a terminal per-campaign decision —
`SELECTED` (creator discovery proceeds) or `REJECTED` (with a rationale). The
`CampaignNicheStatus.SELECTED` value has existed on the model since Slice 3
but was never written to until now.

- `corp/workers/intelligence/niche_selection.py` — `NicheSelector`: loads
  VERIFIED CampaignNiche rows with a non-null `qualification_score`, ranks by
  score descending (ties broken by `canonical_name` for determinism), and
  applies three gates in order: `min_score`, `min_confidence`, then a
  `top_n` cap. Niches failing any gate are `REJECTED` with a specific
  rationale; niches that clear all three, in rank order, up to `top_n`, are
  `SELECTED`.

- `RunType.NICHE_SELECTION` added to the enum in
  `corp/core/models/workflow.py`. No migration needed — `run_type` is stored
  as `String(30)`.

- CLI: `select <campaign_id> [--top-n N] [--min-score F] [--min-confidence F]`
  (defaults: top_n=5, min_score=0.0, min_confidence=0.0).

Reuse, not rebuild: `CampaignNiche` (Slice 3), `qualification_score` /
`confidence` (Slice 12), `start_run`/`finish_run`, no migration needed.

## Acceptance criteria and how each is met

- **Top-N niches by score are selected.**
  `test_selects_top_n_by_score` (3 niches, top_n=2 → top 2 SELECTED, 1 REJECTED).
- **Niches below a score floor are rejected.**
  `test_rejects_below_min_score`.
- **Niches below a confidence floor are rejected.**
  `test_rejects_below_min_confidence`.
- **Already-decided niches (SELECTED/REJECTED) are not re-processed.**
  `test_already_decided_niches_skipped` (query filters on VERIFIED only;
  prior rationale untouched).
- **Niches without a qualification_score are left alone.**
  `test_skips_unqualified_niches` (still VERIFIED, not silently rejected —
  qualification is a separate, required prior step).
- **Empty campaign completes cleanly.**
  `test_empty_campaign`.
- **Ties are broken deterministically.**
  `test_ties_broken_by_name` (same score → alphabetical niche name wins the
  rank, reproducible independent of DB row order).
- **Every VERIFIED, qualified niche reaches a terminal state.**
  `test_all_niches_fit_within_top_n` (no orphaned niches when the pool is
  smaller than top_n) and `test_rejected_niches_marked_terminal`.

## Verification

- `tests/integration/test_niche_selection.py` (9, real Postgres): ranking,
  all three gates, idempotency, unqualified-niche skip, empty campaign,
  tie-breaking, terminal-state coverage.
- Non-DB suite: 304 passed. DB suite: 9 passed. ruff: clean (pre-existing
  UP042 only).
- **Live** (dev DB, campaign "Slice 7 live demo", `--top-n 2`):
  - **#1 SELECTED: Home Espresso Machine Repair** (score=0.6260)
  - **#2 SELECTED: Reef Aquarium Nitrates** (score=0.5122)
  - **#3 REJECTED: Sim Racing Hardware Setup** (score=0.4855) — outside top 2

## Assumptions and open items

- Selection is only run against niches that already have a
  `qualification_score` — it does not implicitly trigger qualification. The
  operator runs `qualify` then `select` as two explicit steps, consistent
  with every other pipeline boundary in this codebase (verify → estimate →
  qualify → select).
- Rejection here is a per-campaign decision (`CampaignNiche.status`), not a
  judgment on the niche itself — `Niche.lifecycle_status` is untouched, so a
  rejected niche in one campaign can still be `ACTIVE` and selected in
  another, per Core Research Invariant #5 (preserve provenance / cross-
  campaign independence, same reasoning as Slice 3's cascade-delete
  decision).
- No support yet for re-running selection with different thresholds on an
  already-decided niche (e.g., loosening `top_n` after seeing the results).
  If that is wanted, a future slice would need to explicitly reset status
  back to VERIFIED first — deliberately not automated, so a human decision
  is never silently overwritten by a re-run.
