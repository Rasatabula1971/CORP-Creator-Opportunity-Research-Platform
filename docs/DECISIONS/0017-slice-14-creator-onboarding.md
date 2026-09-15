# Slice 14 — Creator Onboarding from Selected Niches

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

The bridge between the niche pipeline (Slices 7–13) and the existing
per-creator research pipeline (`collect` / `intelligence` / `intent` /
`research`, pre-dating this work): materialize real `Creator` rows from the
ecosystem search for every SELECTED CampaignNiche in a campaign.

- `corp/workers/acquisition/creator_onboarding.py` — `CreatorOnboarder`:
  loads SELECTED niches, runs a yt-dlp search per niche (reusing
  `SearchAdapter` from Slice 11's ecosystem estimator), and for each unique
  channel get-or-creates a `Creator` + `CreatorPlatformAccount` (identity is
  the existing unique `(platform, handle)` index) and a `CreatorNiche` link
  (identity is the existing unique `(creator_id, niche_id)` index from
  Slice 4 — unused until now). A re-observed link advances
  `last_observed_at` instead of duplicating.

- `RunType.CREATOR_ONBOARDING` added to the enum in
  `corp/core/models/workflow.py`. No migration needed — `run_type` is stored
  as `String(30)`.

- CLI: `onboard <campaign_id> [--search-count N] [--max-per-niche N] [--min-followers N] [--max-followers N]`.

Reuse, not rebuild: `SearchAdapter` protocol (Slice 11), `CreatorPlatformAccount`
unique index (Slice 1), `CreatorNiche` (Slice 4), `start_run`/`finish_run`, no
migration needed.

## Acceptance criteria and how each is met

- **A new channel becomes a Creator + CreatorPlatformAccount.**
  `test_creates_new_creator_and_platform_account`.
- **The same channel seen twice (different niches) reuses one Creator.**
  `test_links_existing_creator_by_platform_handle` (1 created, 1 linked, one
  CreatorPlatformAccount row).
- **A CreatorNiche association is created with provenance.**
  `test_creates_creator_niche_association` (`discovery_run_id` set).
- **Re-running onboarding doesn't duplicate; it advances the timestamp.**
  `test_rerun_updates_last_observed_at_without_duplicating`.
- **Per-niche creator count is capped.**
  `test_respects_max_creators_per_niche` (5 candidates, cap 2 → 2 created).
- **Non-SELECTED niches (still VERIFIED) are skipped.**
  `test_skips_non_selected_niches`.
- **Empty campaign completes cleanly.**
  `test_empty_campaign`.
- **Duplicate channels within one search are deduplicated.**
  `test_dedupes_within_single_search_results`.
- **Optional follower-band filter; unknown reach never blocks.**
  `test_follower_band_filter` (too-small and too-big excluded; unknown
  follower_count included).
- **Multiple niches in one campaign are all processed.**
  `test_multiple_niches_in_one_run`.

## Verification

- `tests/integration/test_creator_onboarding.py` (10, real Postgres): all
  get-or-create paths, dedup (within-run and cross-run), capping, band
  filtering, skip/empty cases.
- Non-DB suite: 304 passed. DB suite: 10 passed. ruff: clean (pre-existing
  UP042 only).
- **Live** (dev DB, campaign "Slice 7 live demo", `--search-count 8 --max-per-niche 5`):
  - **Reef Aquarium Nitrates**: 5 channels found, 5 new creators
  - **Home Espresso Machine Repair**: 5 channels found, 5 new creators
  - 10 creators onboarded total, 0 linked (first run — no prior overlap)
  - Sim Racing Hardware Setup (REJECTED in Slice 13) correctly not processed.

## Assumptions and open items

- Platform is hardcoded to `"youtube"` — the same scope limitation as the
  ecosystem estimator it reuses. A future slice adding Reddit/TikTok
  ecosystem search would need a platform-aware channel-identity strategy
  (YouTube's `UC...` channel IDs don't generalize).
- Onboarded creators start at `CreatorStatus.DISCOVERED` (the model default)
  and are not automatically pushed through `collect`/`research` — that
  remains an explicit, separate operator (or future automation) step, same
  boundary as every other pipeline stage in this codebase.
- The follower-band filter is optional and off by default (`min_followers`/
  `max_followers` both `None`) because yt-dlp search results usually carry
  no `follower_count` at all (Slice 11's finding) — filtering by default
  would silently onboard nothing unless the YouTube API enricher is also
  wired in here, which this slice does not do (kept in scope: pure
  onboarding, not re-estimation).
