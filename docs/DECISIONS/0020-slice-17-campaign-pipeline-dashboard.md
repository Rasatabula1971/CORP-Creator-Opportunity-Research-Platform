# Slice 17 — Campaign Pipeline API + Campaign Dashboard UI

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

Slice 16 gave the API read-only visibility into campaigns, niches, and
creators. This slice completes the loop: the API can now **create**
campaigns and **trigger** every campaign pipeline stage, and a full React
dashboard lets operators manage the entire campaign lifecycle from the
browser instead of the CLI.

### Backend

- `POST /campaigns` — create a campaign (draft status, returns
  `CampaignResponse`).
- `POST /campaigns/{id}/{stage}` — trigger any of the 9 campaign pipeline
  stages (`discover`, `candidates`, `canonicalize`, `verify`,
  `estimate-ecosystem`, `qualify`, `select`, `onboard`,
  `research-campaign`) as a background job. Returns `JobResponse` (202).
  Guards: campaign must exist (404), stage must be valid (422), no active
  job for this campaign (409), `discover` requires `source` + `query` (422).
- `CAMPAIGN_PIPELINES` constant and `run_campaign_pipeline()` work function
  in `jobs.py` — handles all 9 stages by instantiating the correct worker
  classes with proper session/provider lifecycle.
- `campaign_id` field on `JobResponse` — jobs can now be associated with
  campaigns (in addition to the existing `creator_id`).
- `JobRegistry.active_for_campaign()` — prevents concurrent jobs per
  campaign, same pattern as `active_for()` for creators.
- `JobRegistry.list()` accepts optional `campaign_id` filter.

### Frontend

- **Types** (`types.ts`): `Campaign`, `CampaignCreateInput`,
  `CampaignNiche`, `CampaignNicheStatus`, `Niche`.
- **Hooks** (`hooks.ts`): `useCampaigns`, `useCampaign`,
  `useCreateCampaign`, `useCampaignNiches`, `useCampaignCreators`,
  `useStartCampaignPipeline`.
- **CampaignsPage** — campaign list table + inline create form with
  configurable niche count, creators per niche, and follower range.
- **CampaignDetailPage** — campaign header with status badge, pipeline
  control panel (9 stages, discover has source/query inputs), active job
  status card with result display, niches table (status, score, creator
  count, selected), onboarded creators table.
- **Routing**: `/campaigns` and `/campaigns/:id` routes added.
- **Navigation**: "Campaigns" link in the header nav bar between "Research
  Runs" and "Jobs".
- **Status colors**: added badge colors for `draft`, `active`, `paused`,
  `candidate`, `canonical`, `verified`, `qualified`, `selected`.

## Acceptance criteria and how each is met

- **Campaigns can be created from the UI.**
  `POST /campaigns` endpoint + `CreateCampaignForm` component +
  `test_create_campaign`, `test_create_campaign_defaults`.
- **Every pipeline stage is triggerable from the API.**
  `POST /campaigns/{id}/{stage}` with validation —
  `test_start_campaign_pipeline_unknown_stage`,
  `test_start_discover_requires_source_and_query`,
  `test_campaign_pipeline_conflict`.
- **Pipeline stages are triggerable from the UI.**
  `CampaignDetailPage` pipeline control panel with per-stage buttons and
  discover-specific source/query inputs.
- **Job progress is visible in the UI.**
  Active job card with status badge, error display, and JSON result viewer
  (same pattern as `CreatorDetailPage`).
- **Campaign niches and creators are visible in the dashboard.**
  Niches table and creators table in `CampaignDetailPage`, powered by
  existing read endpoints from Slice 16.
- **No concurrent campaign jobs.**
  `active_for_campaign()` guard + `test_campaign_pipeline_conflict`.

## Verification

- `tests/api/test_campaign_endpoints.py` — 6 new tests (create, defaults,
  unknown stage, not found, discover validation, conflict) added to the
  existing 9 from Slice 16.
- Python syntax verified (`py_compile`).
- TypeScript type check clean (`tsc --noEmit`).

## Assumptions and open items

- Campaign status transitions (draft → active → completed) are not yet
  automated — a future slice could advance status as pipeline stages
  complete.
- No campaign edit/delete endpoints yet — campaigns are immutable once
  created (consistent with the evidence-first, append-only design).
- The pipeline control UI doesn't enforce stage ordering — an operator can
  run stages in any order. The workers themselves are idempotent and
  validate preconditions internally.
