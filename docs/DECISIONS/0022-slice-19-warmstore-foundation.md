# Slice 19 — WarmStore Foundation

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

The first half of the tiered-storage design: a SQLite-backed warm store
for bulk data that will eventually live on a flash drive / external SSD,
keeping Supabase Postgres within the free-tier 500 MB limit.

This slice ships the foundation — schema, async store class, CLI tools —
without rewiring any existing pipeline (that is Slice 20).

### New package: `corp/warmstore/`

- **`schema.py`** — 8 SQLAlchemy Core `Table` definitions mirroring the
  Postgres models that hold bulk data:
  1. `evidence` (raw_text)
  2. `problem_observations` (embedding as BLOB, text)
  3. `content_items` (title, description, topics/extra as JSON text)
  4. `audience_interactions` (comment text)
  5. `metrics_snapshots` (extra as JSON text)
  6. `research_queries` (query text, archive_reference)
  7. `creator_scores` (superseded scores, component_scores/diagnostics as JSON)
  8. `opportunity_scores` (same as creator_scores)

  Type adaptations: `JSONB → TEXT` (JSON string), `pgvector Vector(384) → BLOB`,
  `Enum → TEXT`, `Boolean → Integer`.

- **`store.py`** — `WarmStore` class with:
  - `init_db()` — create all tables (idempotent via `CREATE TABLE IF NOT EXISTS`)
  - `put_*()` — 8 typed methods, one per table, using `INSERT OR REPLACE`
    for idempotent writes. Accepts dicts with enum instances, ISO datetime
    strings, and Python dicts/lists (auto-serialized to JSON text).
  - `get_evidence_text(ids)` — batch lookup returning `{id: raw_text}`
  - `get_observation_embeddings(ids)` — batch lookup returning `{id: bytes}`
  - `count_rows()` — per-table row counts
  - `export_jsonl(out_dir)` — dump every table to a JSONL file

### Config

- `warm_store_path` added to `Settings` (default `corp_data/warm.db`).
- `.env.example` updated with `WARM_STORE_PATH`.

### CLI

Three new subcommands on `python -m corp.workers.run`:

- `warm-init` — create/initialize the SQLite database file
- `warm-status` — print per-table row counts and the database path
- `warm-export <out_dir>` — export all tables to JSONL files

### Dependency

- `aiosqlite>=0.20,<1` added to `pyproject.toml`.

## Acceptance criteria and how each is met

- **SQLite database can be created at a configurable path.**
  `warm_store_path` in Settings, `WarmStore(path)`, `warm-init` CLI.
- **All 8 bulk-data tables exist with correct columns.**
  `schema.py` defines them; `metadata.create_all` creates them.
- **Data can be written and read back correctly.**
  Smoke test verifies put/get round-trip for evidence text, observation
  embeddings, content items with JSON columns, interactions, metrics,
  and superseded scores.
- **Writes are idempotent (INSERT OR REPLACE).**
  Smoke test verifies re-inserting the same ID updates the row.
- **JSONB columns round-trip through JSON text.**
  Smoke test verifies `topics: ["a", "b"]` and `extra: {"k": 1}` serialize
  on write.
- **Embedding BLOB round-trips.**
  Smoke test verifies 1536-byte embedding stored and retrieved intact.
- **CLI tools work without Postgres.**
  `warm-init`, `warm-status`, `warm-export` use lazy imports; only the
  warm store is required.

## Verification

- Python syntax: `py_compile` clean on all 5 changed/new files.
- Smoke test: 7 put operations, 2 get operations, count_rows, idempotent
  re-insert, export — all assertions pass.

## Assumptions

- Pipelines continue writing to Postgres only until Slice 20 wires in
  dual writes. The warm store is write-ready but not yet integrated.
- No migration tooling — the SQLite schema is created fresh by
  `metadata.create_all`. Schema changes in future slices will either
  recreate the database (bulk data is recoverable from Postgres) or use
  manual ALTER TABLE.
- Embeddings are stored as raw bytes (the caller is responsible for
  numpy serialization/deserialization). A 384-dim float32 vector is
  1,536 bytes.
- Foreign keys are not enforced in SQLite — these are copies of
  Postgres data, and referential integrity is maintained by the
  source of truth.
