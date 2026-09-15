# Slice 6 — Research Query Ledger

**Status:** ACCEPTED
**Date:** 2026-09-14
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, Slice 6 / §12 / §13 / ADR-006

## What shipped

`ResearchQuery` (model, schema, migration, tests) with every field from §12, linked
to `ResearchRun` under ADR-006, plus the persistence service this slice explicitly
scopes in: `corp/core/research/ledger.py` with `record_query()` and
`find_queries()`. `find_queries(source=, query=)` is the "has this exact query been
used, on which source, with what yield?" path from §13.

`(source, query)` is indexed but deliberately **not** unique. Re-running a query in a
later run is expected; the per-run history of yields is exactly what a later slice
needs to judge staleness and usefulness decay.

## Problem found and fixed during this slice

`executed_at` was first written with a bare `server_default=now()`. In Postgres,
`now()` is the transaction start time, so every query recorded inside one
transaction would share a timestamp — fifty searches over ten minutes all stamped
identically. For a ledger whose purpose is recording *when* each search ran, that is
wrong. Fixed to a client-side `datetime.now(UTC)` default (the same convention
`start_run()` already uses for `started_at`), with `server_default` retained only
as a fallback for raw SQL inserts. `test_query_executed_at_is_per_query_not_per_transaction`
pins it.

**Lesson worth keeping:** `server_default=func.now()` is right for bookkeeping columns
(`created_at`, `updated_at`) and wrong for event-time columns. Any future
"when did X happen" column should take a client-side default.

## Placement decision

The ledger service lives in `corp/core/research/`, a new core subpackage, not in
`workers/`. It depends only on models and SQLAlchemy; both acquisition (Slice 7) and
future verification pipelines will call it; `workers → core` is the permitted
direction; and session-aware helpers already exist in core
(`corp/core/state/transitions.py`). Both import-linter contracts hold.

## Assumptions

- "Persistence API/service" means service functions, not HTTP endpoints, consistent
  with the gate assessment (§28) deferring API contracts to slices that expose new
  behavior.
- Exact query matching is literal and case-sensitive (a test documents this).
  Semantic/equivalent-query matching and cooldown heuristics are out of scope per the
  slice definition.
- `ResearchQueryStatus` is just SUCCEEDED / FAILED. The doc says "status/error"
  without enumerating values; two states cover "did the search execute or not", and
  `error` carries the detail.

## Unresolved, pre-existing issues

Unchanged from Slices 1–5: `tests/integration/test_migration.py` and
`tests/api/test_endpoints.py` remain broken due to hardcoded assumptions from a
different machine. Not touched.
