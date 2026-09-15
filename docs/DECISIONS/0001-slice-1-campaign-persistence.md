# Slice 1 — Campaign Persistence

**Status:** ACCEPTED
**Date:** 2026-09-14
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, Slice 1

## What shipped

`Campaign` as a standalone table (model, schema, migration, tests) with the fields and
defaults from §12 of the architecture doc. No foreign keys into any existing table, no
API endpoints, no repository/service layer (matches the rest of CORP, which queries
models directly rather than through a repository abstraction).

## Problems found and fixed during this slice

1. **Alembic double-created the enum type.** The migration called
   `campaign_status.create(op.get_bind(), checkfirst=True)` explicitly, but
   `op.create_table` also auto-creates the Postgres enum type from the column
   definition. First run failed with `DuplicateObject`. Fix: removed the explicit
   `.create()` call and let `op.create_table` handle it.

2. **Enum values didn't match codebase convention.** The migration stored the Postgres
   enum values in lowercase (`'draft'`, `'active'`, ...), but every existing enum in
   CORP (`CreatorStatus`, `DecisionType`, `Gate`, ...) stores the Python enum member's
   *name* in uppercase (`'DRAFT'`, `'ACTIVE'`, ...), since `sa.Enum(SomePyEnum)` binds
   by name, not value, by default. First test run failed with
   `invalid input value for enum campaignstatus: "DRAFT"`. Fix: changed the migration's
   literal values to uppercase to match.

3. **`tests/conftest.py` pointed at the wrong local Postgres port** (5432, the
   default) instead of 5433, the port this machine's actual Postgres 16 install uses.
   Fixing this uncovered a second, more serious issue: the user's shell profile
   already exports a `DATABASE_URL` for an unrelated project (CIP), and switching the
   port via `os.environ.setdefault(...)` let that ambient value leak into CORP's test
   suite, corrupting the async engine (`InvalidRequestError: psycopg2 is not async`).
   **Fix:** introduced `CORP_TEST_DATABASE_URL` / `CORP_TEST_DATABASE_URL_SYNC` as a
   dedicated override, with `os.environ["DATABASE_URL"] = ...` (forced, not
   `setdefault`) so CORP's tests can never silently inherit another project's
   connection string. This is a real footgun worth remembering: never use
   `setdefault` for test-database isolation when the ambient environment might
   already define the same variable name for something else.

## Unresolved, pre-existing issues (not touched — out of scope for Slice 1)

- `tests/integration/test_migration.py` hardcodes a Linux path
  (`cwd="/home/user/CORP-Creator-Opportunity-Research-Platform"`) and
  `localhost:5432`, both wrong for this Windows machine. Both tests in that file fail
  regardless of any change made here.
- `tests/api/test_endpoints.py` requires the FastAPI app's default DB session, which
  reads `DATABASE_URL` from `corp.config.settings` rather than the test override —
  needs a local Postgres on the default port 5432, which nothing on this machine
  listens on (only 5433 is installed). 12 tests error with `ConnectionRefusedError`.
- Local Postgres 16 (port 5433) has no pgvector extension installed. Integration tests
  that touch any `Vector`-typed column must run against the `corp_test` database
  created on the Supabase project instead (`CORP_TEST_DATABASE_URL` pointed there for
  this slice's verification). A fully local, pgvector-capable Postgres was previously
  investigated and deferred (compiling pgvector on Windows needs Visual Studio Build
  Tools) in favor of Supabase for the main dev database; the same tradeoff now applies
  to the test database.

## New constraint for future slices

Any migration that adds a `sa.Enum` column must use uppercase member names as the
literal enum values, matching every existing enum in the codebase. Do not call
`.create()` on the enum explicitly inside `op.create_table`-based migrations.
