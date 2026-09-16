# Slice 3 — Campaign ↔ Niche Relationship

**Status:** ACCEPTED
**Date:** 2026-09-14
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, Slice 3

## What shipped

`CampaignNiche` as a standalone join table (model, schema, migration, tests) with
every field from §12: discovery_rank, qualification_score, confidence,
research_completeness, creator_count_observed, target_band_creator_count, status,
selected, rationale. Unique on `(campaign_id, niche_id)` — the same niche can appear
in many campaigns, but only once within a given campaign.

## Problems found during this slice

None. Both migration lessons from Slice 1 (don't double-create the enum type; match
the codebase's uppercase-enum-value convention) were applied directly, and the
migration passed against `corp_test` on the first attempt.

## Cascade-delete decision

`Campaign.campaign_niches` cascades on delete (these rows belong to the campaign).
`Niche.campaign_niches` does **not** cascade — a niche's cross-campaign history must
survive even if one of the campaigns referencing it were ever deleted, per Core
Research Invariant #5 (preserve provenance).

## Assumptions

- `CampaignNicheStatus` values (`discovered / verified / selected / rejected`) aren't
  literally specified in the doc; inferred from the Stage A → Stage B → selection
  flow in §15–16, and kept deliberately distinct from `Niche.lifecycle_status` —
  one is the niche's canonical state, the other is this campaign's own progress
  with it.

## Unresolved, pre-existing issues

Unchanged from Slices 1–2: `tests/integration/test_migration.py` and
`tests/api/test_endpoints.py` remain broken due to hardcoded assumptions from a
different machine. Not touched.
