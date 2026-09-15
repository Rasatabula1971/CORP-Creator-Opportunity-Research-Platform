# Slice 11 — Creator Ecosystem Size Estimator

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

For each VERIFIED niche in a campaign, a yt-dlp search discovers unique
creator channels active in the niche and populates `creator_count_observed`
and `target_band_creator_count` on the CampaignNiche row. No API key, no
LLM, no cost.

- `corp/workers/intelligence/ecosystem_estimator.py` — `EcosystemEstimator`:
  loads VERIFIED CampaignNiche rows, runs `ytsearchN:<niche name>` via the
  existing yt-dlp adapter, deduplicates channels by ID, counts total unique
  creators and the subset whose follower count falls within a configurable
  band (default 10K–200K, the partnership sweet spot).

- `RunType.CREATOR_DISCOVERY` added to the enum in
  `corp/core/models/workflow.py`. No migration needed — `run_type` is stored
  as `String(30)`.

- CLI: `estimate-ecosystem <campaign_id> [--search-count N] [--min-followers N] [--max-followers N]`.

- `YouTubeAPIEnricher` — optional second-pass enrichment when
  `YOUTUBE_API_KEY` is set. Batches channel IDs (up to 50 per call, 1 quota
  unit each) via `channels().list(part="statistics")` to get real subscriber
  counts. Falls back gracefully on API failure (logs warning, keeps yt-dlp
  counts). Only resolves channel IDs matching the `UC...` 24-char format.

Reuse, not rebuild: `YtDlpAdapter` (Slice 7), `CampaignNiche` (Slice 3),
`start_run`/`finish_run`, no migration needed.

## Acceptance criteria → how each is met

- **Unique creators are counted per niche.**
  `test_estimates_single_niche` (4 creators, 2 in target band).
- **Duplicate channels are deduplicated.**
  `test_deduplicates_channels` (same channel_id twice → 1 creator).
- **Creators without follower data excluded from target band.**
  `test_no_follower_count_excluded_from_band` (null follower_count → not in band).
- **Multiple niches in one campaign.**
  `test_multiple_niches` (2 niches with different creator counts).
- **Non-verified niches are skipped.**
  `test_skips_non_verified_niches` (DISCOVERED niche → 0 checked).
- **Empty campaign completes cleanly.**
  `test_empty_campaign_completes`.
- **Empty search results handled.**
  `test_search_empty_results` (0 creators, counts set to 0).

## Verification

- `tests/integration/test_ecosystem_estimator.py` (10, real Postgres): all
  counting paths, dedup, follower filtering, skip logic, empty cases, plus
  enrichment (subscriber count population, graceful fallback on API failure,
  non-UC channel ID filtering).
- Non-DB suite: 304 passed. DB suite: 10 passed. ruff: clean.
- **Live** (dev DB, campaign "Slice 7 live demo", search_count=10):
  - **Sim Racing Hardware Setup**: 7 creators observed, 0 in target band
  - **Reef Aquarium Nitrates**: 9 creators observed, 0 in target band
  - **Home Espresso Machine Repair**: 10 creators observed, 0 in target band
  - Target band counts are 0 because yt-dlp search results return video
    metadata, not channel profiles — `follower_count` is null for search
    hits. This is correct behavior; a future slice could add a second-pass
    channel resolution to fetch subscriber counts.

## Assumptions and open items

- Without `YOUTUBE_API_KEY`, `target_band_creator_count` relies on
  `follower_count` from yt-dlp metadata, which is typically null for search
  results (only available on channel profile pages). With the API key set,
  the `YouTubeAPIEnricher` resolves real subscriber counts at 1 quota unit
  per 50 channels — negligible against the 10K/day free tier.
- `search_count` defaults to 20 (reduced to 10 for the live test to keep
  runtime short). Higher values discover more creators but take longer.
- The estimator uses the existing `YtDlpAdapter` unmodified. No new adapter
  code was needed.
