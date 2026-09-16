# Slice 20 — WarmStore Pipeline Integration

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

Dual-write integration: every pipeline that persists bulk data to
Postgres now mirrors the same rows into the SQLite warm store
immediately after `session.flush()`.

### New module: `corp/warmstore/sync.py`

The glue layer between ORM pipelines and the `WarmStore`. Contains:

- **`model_to_dict()`** — extracts column values from a SQLAlchemy ORM
  instance as a plain dict, converting enum `.value` attributes.
- **`_get_store()`** — lazy-initializes a module-level `WarmStore`
  singleton from `settings.warm_store_path`.
- **7 `mirror_*()` functions** — one per data type: `mirror_evidence`,
  `mirror_observations`, `mirror_content_items`, `mirror_interactions`,
  `mirror_metrics`, `mirror_research_queries`, `mirror_scores`.

Each mirror function is fire-and-forget: catches all exceptions, logs a
warning, and returns. Pipelines never fail because of a warm-store error.

### Modified pipelines

| Pipeline file | Mirror calls added |
|---|---|
| `workers/acquisition/collector.py` | `mirror_evidence`, `mirror_content_items`, `mirror_interactions`, `mirror_metrics` (×2) |
| `workers/intelligence/pipeline.py` | `mirror_observations` (×2: audience + creator side) |
| `workers/acquisition/discovery.py` | `mirror_evidence` |
| `core/research/ledger.py` | `mirror_research_queries` |
| `workers/intelligence/scoring_pipeline.py` | `mirror_scores` (×2: opportunity + creator) |

**Total: 10 mirror call sites across 5 files.**

### Pattern

Every call site follows the same structure:

1. `session.add(row)` — stage in Postgres (source of truth)
2. `await session.flush()` — assign PK, write to Postgres WAL
3. `await mirror_*(row)` — best-effort copy to SQLite

The mirror call receives the ORM instance after flush, so all
server-generated columns (id, timestamps) are populated.

## Acceptance criteria and how each is met

- **All bulk-data write paths have a mirror call.**
  10 call sites cover evidence, observations, content items,
  interactions, metrics snapshots, research queries, and scores.
- **Mirror calls are fire-and-forget.**
  Every `mirror_*()` wraps its body in `try/except Exception` and
  logs a warning on failure.
- **Import-linter contracts are not violated.**
  `warmstore.sync` imports only from `corp.warmstore.store` and
  `corp.config`. Pipeline files import from `corp.warmstore.sync`,
  which is allowed (warmstore is not in workers or api).
  `core.research.ledger` imports from `corp.warmstore.sync` — core
  importing warmstore is allowed (no contract forbids it).
- **No pipeline logic is changed.**
  The only modifications are: (a) importing mirror functions,
  (b) capturing ORM instances in named variables where needed,
  (c) calling the mirror function after flush.

## Verification

- `py_compile` clean on all 6 changed/new files.
- Import-linter contracts: warmstore imports only store + config;
  core.research.ledger imports warmstore (allowed); workers import
  warmstore (allowed).

## Assumptions

- Warm store is optional at runtime: if `warm_store_path` is missing
  or SQLite is unavailable, `_get_store()` returns `None` and all
  mirror calls no-op.
- `session.flush()` must complete before the mirror call so that
  server-generated PKs are available. The mirror functions do not
  participate in the Postgres transaction.
- `mirror_observations` handles embedding serialization: if the
  observation has a non-bytes embedding attribute, it converts via
  `tobytes()` or `bytes()`.
