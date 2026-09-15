# Slice 16 — Campaign & Niche API Visibility

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

Nine slices (7–15) built the entire niche pipeline — discovery through
campaign-wide research — with zero API surface for any of it. The only way
to see campaign/niche state was the CLI or a direct DB query. This slice
closes that gap with read endpoints, reusing the Step 8 console's existing
FastAPI app, auth, and error-handling conventions unmodified.

- `GET /campaigns` — paginated list (`X-Total-Count` header, same pattern
  as `GET /creators`).
- `GET /campaigns/{campaign_id}` — detail, 404 on unknown id.
- `GET /campaigns/{campaign_id}/niches[?status=]` — every CampaignNiche row
  for the campaign with the linked Niche nested (name, lifecycle status,
  etc.), ordered by `qualification_score` descending (nulls last) so the
  strongest niches surface first; optional status filter.
- `GET /campaigns/{campaign_id}/creators[?niche_status=]` — distinct
  creators reachable via `CreatorNiche` from the campaign's niches, default
  `niche_status=selected` (the useful default: "who's actually in play"),
  filterable to see creators under any other CampaignNicheStatus.
- `CampaignNicheDetailResponse` (new schema) — `CampaignNicheResponse` plus
  a nested `niche: NicheResponse`, so a client isn't forced to make a
  second round-trip to name the niche.

No new models, no migration — every field already existed
(`CampaignNicheResponse`, `NicheResponse` from Slices 1–3).

## Acceptance criteria and how each is met

- **Campaigns are listable and fetchable.**
  `test_list_campaigns`, `test_get_campaign`, `test_get_campaign_not_found`.
- **Niches under a campaign show qualification/selection state, not just
  IDs.**
  `test_list_campaign_niches_includes_niche_detail` (nested niche name,
  correct score-descending order).
- **Niches are filterable by status.**
  `test_list_campaign_niches_filters_by_status`.
- **An unknown campaign 404s consistently across every nested route.**
  `test_list_campaign_niches_unknown_campaign`,
  `test_list_campaign_creators_unknown_campaign`.
- **Creators default to the useful view (selected-niche creators).**
  `test_list_campaign_creators_defaults_to_selected`.
- **The niche-status filter actually changes the creator set.**
  `test_list_campaign_creators_niche_status_filter_excludes` (querying
  `verified` when the only linked niche is `selected` returns empty).

## Verification

- `tests/api/test_campaign_endpoints.py` (9, real Postgres, `httpx` +
  `ASGITransport` against the real app — no server process, same pattern as
  the existing Step 8 test suite).
- Full `tests/api` suite: 36 passed (12 pre-existing + 9 new + others;
  confirms no regression — the "broken, needs a running server" note in
  earlier decision records turned out to be stale, the suite runs clean via
  `ASGITransport`).
- Non-DB suite: 304 passed. ruff: clean.
- **Live** (dev DB, campaign "Slice 7 live demo", via `ASGITransport`, no
  server process):
  - `GET /campaigns` → `Slice 7 live demo`
  - `GET /campaigns/{id}/niches` → 3 rows: Home Espresso (selected,
    0.626), Reef Aquarium (selected, 0.5122), Sim Racing (rejected, 0.4855)
    — correctly score-ordered.
  - `GET /campaigns/{id}/niches?status=selected` → 2 rows.
  - `GET /campaigns/{id}/creators` → 10 creators (the exact set Slice 14
    onboarded), names resolved correctly (Lance Hedrick, Mad Hatter's Reef,
    Bulk Reef Supply, etc.).

## Assumptions and open items

- Read-only. No write endpoints for triggering pipeline stages (`discover`,
  `verify`, `qualify`, `select`, `onboard`, `research-campaign`) from the
  API — those remain CLI/operator actions, consistent with every other
  pipeline boundary in this codebase (a human or automation runs the
  pipeline; the API is for *reviewing* its output, matching the existing
  Gate A pattern where `/creators/{id}/decisions` records a human call but
  nothing in the API *runs* research).
- `niche_status` filter on the creators endpoint takes a single
  `CampaignNicheStatus` rather than a list — a creator visible under two
  different statuses in the same campaign (impossible today, since a niche
  has exactly one status) isn't a real scenario, so this wasn't generalized
  further.
- No campaign-level "roll-up" endpoint (e.g. total qualified niches, total
  onboarded creators, batch research progress) — a future slice could add
  one if the console needs a dashboard view; today a client composes it
  from the three endpoints above.
