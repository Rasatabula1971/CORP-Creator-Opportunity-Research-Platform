# Slice 4 — Creator ↔ Niche Relationship

**Status:** ACCEPTED
**Date:** 2026-09-14
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, Slice 4

## What shipped

`CreatorNiche` as a standalone many-to-many association table (model, schema,
migration, tests) with every field from §12: first_observed_at, last_observed_at,
confidence, discovery_run_id. Unique on `(creator_id, niche_id)` — a creator may
belong to several niches, a niche to several creators, once each.

`Creator.niche` (the legacy string field) is explicitly untouched, per the doc's own
instruction to keep it for backward compatibility and deprecate it deliberately
later, not as a side effect of this slice.

## Problems found during this slice

None. Both migration lessons from Slice 1 applied directly; the migration passed
against `corp_test` on the first attempt.

## Compatibility verification

Two tests exist specifically to prove the doc's compatibility requirement, not just
to exercise the new table:
- `Creator.niche` still reads/writes correctly and coexists with `CreatorNiche` rows
  referencing the same creator.
- The full pre-existing creator + `ResearchRun` creation path (unrelated to niches)
  is unaffected.

## Cascade decision

Neither `Creator.creator_niches` nor `Niche.creator_niches` cascades on delete — same
reasoning as Slice 3's `Niche.campaign_niches`: this association is durable history,
not owned exclusively by either side.

## Unresolved, pre-existing issues

Unchanged from Slices 1–3: `tests/integration/test_migration.py` and
`tests/api/test_endpoints.py` remain broken due to hardcoded assumptions from a
different machine. Not touched.
