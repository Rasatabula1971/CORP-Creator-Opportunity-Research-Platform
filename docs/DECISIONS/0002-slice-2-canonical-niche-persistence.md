# Slice 2 — Canonical Niche Persistence

**Status:** ACCEPTED
**Date:** 2026-09-14
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, Slice 2

## What shipped

`Niche` and `NicheAlias` as standalone tables (model, schema, migration, tests) with
the fields from §12. Both `Niche.canonical_name` and `NicheAlias.alias` are unique
**case-insensitively** (Postgres functional indexes on `lower(...)`), since the doc's
stated purpose for aliasing is preventing "fake diversity" in the final niche
selection — a differently-cased duplicate is exactly the failure mode that matters.

## Problems found during this slice

None new. The migration-authoring lessons from Slice 1 (don't double-create enum
types; match the codebase's uppercase-enum-value convention) were applied directly
and both migrations passed on the first attempt against `corp_test`.

One self-caught mistake, not a bug: when running the verification test suite I
initially exported plain `DATABASE_URL`/`DATABASE_URL_SYNC` instead of the
`CORP_TEST_DATABASE_URL` override introduced in Slice 1 — conftest.py correctly
ignored it and fell back to the (unreachable, on this machine) local default,
producing 28 `ConnectionRefusedError`s. This is the isolation fix working as
designed, not a regression; corrected by using the right variable name.

## Assumptions

- `NichePolicyClass` values (`standard / restricted / excluded`) match §6 directly.
  The "configuration-driven, not scattered through business logic" requirement is
  read as governing the *rules that assign* a policy class (a later, discovery-facing
  slice) — this slice only persists the result.
- `NicheLifecycleStatus` adds a `CANDIDATE` state ahead of §7's documented
  ACTIVE/EXPAND → COOLDOWN → RECHECK_DUE cycle, as the default for a niche that
  exists but hasn't been through verification (Stage B) yet — mirrors `Creator`
  starting at `DISCOVERED`.
- No repository/service layer, no API endpoints — same reasoning as Slice 1.

## Unresolved, pre-existing issues

Unchanged from Slice 1: `tests/integration/test_migration.py` and
`tests/api/test_endpoints.py` remain broken due to hardcoded assumptions from a
different machine (Linux path, local Postgres on the default port). Not touched.
