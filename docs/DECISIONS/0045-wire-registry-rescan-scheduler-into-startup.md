# ADR-0045 — Wire Registry Re-scan Scheduler into App Startup

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 finishing plan item 2 (post-T21), T10 (ADR-0040)

## Context

T10 (ADR-0040) shipped `RegistryRescanScheduler` as a tested-but-unwired module,
following the same precedent as T7 and T9: build the logic first, wire it later.
The scheduler finds WATCHING dossiers whose niche's `next_recheck_at` has passed,
regenerates them via T6's `DossierGenerator`, and advances the recheck clock —
fulfilling the Stage 4 invariant that watched dossiers are automatically re-scored
within 24 hours.

After T21 completed the scoring integration, the user directed working down a
finishing list. This is item 2: wire the scheduler into the FastAPI app lifecycle
so it actually runs.

## Decisions

### FastAPI lifespan context manager

Added an `async def lifespan(app)` generator to `corp/api/app.py` using
`contextlib.asynccontextmanager`. It creates a `RegistryRescanScheduler` with
the app's `async_session` factory and `settings.scoring_rules_path`, calls
`start()` on entry, and `stop()` on exit. The `lifespan` parameter is passed
to the `FastAPI()` constructor, replacing the (absent) legacy `on_event` pattern.

### Graceful degradation on construction failure

The scheduler's constructor synchronously reads `rules/niche_discovery_prompt.yaml`
(via `DiscoveryConfig.from_rules`) to determine `recheck_days`. If this file is
missing or malformed, construction would fail. Rather than crashing the entire API
server, the lifespan handler catches the exception, logs it at ERROR level, and
continues serving requests without auto-rescan. The scheduler is an auxiliary
feature — the API must remain available even if it cannot start.

### No new configuration

The scheduler's constructor already defaults to sensible values:
- `interval_seconds=3600` (hourly tick, well within the 24-hour SLA)
- `niche_rules_path="rules/niche_discovery_prompt.yaml"` (same file used by
  niche discovery itself — one source of truth for `recheck_days`)

No new settings were added to `corp/config.py`. The only config value consumed
from settings is `scoring_rules_path`, which already exists.

### Existing tests unaffected

`httpx.AsyncClient` with `ASGITransport` does not exercise ASGI lifespan events
by default, so all 74 pre-existing API tests continue to pass unchanged.

## Files changed

| File | Change |
| --- | --- |
| `corp/api/app.py` | Added `lifespan` async context manager that starts/stops `RegistryRescanScheduler`. Passed `lifespan=lifespan` to `FastAPI()`. |
| `tests/api/test_lifespan.py` | New: 4 unit tests verifying start/stop lifecycle, correct config passing, stop-on-exception, and graceful degradation on construction failure. |

No migration. No model changes. No new dependencies.

## Verification

- `mypy --strict` clean on `corp/api/app.py`.
- `ruff check` clean on all changed files.
- `tests/api/test_lifespan.py`: 4 passed.
- Full `tests/api/`: 78 passed (up from 74, the 4 new tests).

## Consequences

- When the CORP API server starts, the registry re-scan scheduler begins its
  hourly tick loop automatically. WATCHING dossiers whose niche recheck window
  has passed will be regenerated and resurfaced as PENDING_REVIEW.
- The scheduler is stopped cleanly on shutdown (SIGTERM/Ctrl+C), preventing
  orphaned asyncio tasks.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF — the same pre-existing dev-environment changes disclosed
in every ADR since T4. Not staged as part of this task's commit.
