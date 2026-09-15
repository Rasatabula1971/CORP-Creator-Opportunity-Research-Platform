# ADR-0029 — Slice 26: Multi-Source Niche Discovery + Source Health Tracking

**Status:** Accepted
**Date:** 2026-09-15

## Context

Through Slices 22–25, CORP wired in 8 niche-signal adapters (Stack Exchange,
search demand, Amazon reviews, marketplace, Hacker News, Wikipedia, Google
Trends, App Store). However, `NicheDiscoveryCollector` runs one query against
one adapter at a time — there is no orchestrator that fans a niche keyword
across all relevant sources.

The user also requested that tolerated sources (App Store RSS, pytrends,
Google autocomplete) be monitored and "after continued no response they are
disconnected." No such infrastructure existed.

## Decision

### 1. Source Health Tracker (`corp/workers/adapters/health.py`)

A circuit-breaker for adapter sources:

| State | Meaning | Trigger |
|---|---|---|
| `healthy` | Normal operation. | Default, or success after degraded/disconnected. |
| `degraded` | Consecutive failures exceeded `HEALTH_DEGRADE_AFTER` (default 3). | Still attempted in runs; logged as warning. |
| `disconnected` | Consecutive failures exceeded `HEALTH_DISCONNECT_AFTER` (default 6). | Skipped in multi-source runs. |

A disconnected source gets one **probe attempt** after a cooldown period
(`HEALTH_PROBE_COOLDOWN_SECONDS`, default 1 hour). If the probe succeeds,
the source recovers to healthy. If it fails, it stays disconnected and the
cooldown resets.

Health state is persisted as JSON under `CORP_DATA_PATH/adapter_health.json`.
This is operational state — loss is non-critical.

### 2. Multi-Source Niche Discovery (`corp/workers/acquisition/multi_discovery.py`)

Given a campaign and a keyword, `MultiSourceDiscovery.discover()`:

1. Builds every configured niche adapter via the registry.
2. Checks each source's health — disconnected sources are skipped.
3. Runs healthy adapters sequentially (respects rate limits).
4. Persists evidence under a single `NICHE_DISCOVERY` `ResearchRun`.
5. Records per-source yields in the research ledger.
6. Updates the health tracker on success/failure.
7. Archives all collected items as JSONL.

The run's `stats.extra["per_source"]` contains per-adapter status, yields,
and health state — enabling the dashboard to show which sources contributed
and which are degraded.

### Key design choices

| Choice | Rationale |
|---|---|
| Sequential adapter execution | Respects per-source rate limits; avoids thundering herd against multiple APIs simultaneously. |
| Single run for all sources | One `ResearchRun` with multiple `ResearchQuery` rows (one per source) — matches the "one research action" mental model. |
| JSON file for health state | Operational state, not research data. No DB migration needed. Loss is non-critical — defaults to healthy. |
| Circuit-breaker thresholds as config | Different operators may have different tolerance for failures depending on their network. |
| Probe-on-cooldown recovery | Avoids permanent disconnection; tolerated sources that come back online are automatically re-enabled. |
| `NICHE_PLATFORMS` constant | Separates niche adapters from creator-bound ones; only niche adapters participate in multi-source discovery. |

### Files changed

| File | Change |
|---|---|
| `corp/workers/adapters/health.py` | New — source health tracker with circuit-breaker logic. |
| `corp/workers/acquisition/multi_discovery.py` | New — multi-source niche discovery orchestrator. |
| `corp/config.py` | Added `health_degrade_after`, `health_disconnect_after`, `health_probe_cooldown_seconds`, `niche_discovery_platforms`. |
| `.env.example` | Documented new env vars. |
| `tests/workers/test_source_health.py` | 13 tests covering all health states and transitions. |
| `tests/workers/test_multi_discovery.py` | 10 tests covering fan-out, skip, failure continuation, dedup, archiving. |

## Consequences

* A single `discover(campaign_id, "python automation")` call now queries all
  8 niche sources and aggregates evidence under one run.
* Tolerated sources that repeatedly fail are automatically disconnected and
  probed for recovery — the user's "monitored and disconnected" requirement.
* The health tracker is reusable by any future pipeline that needs source
  reliability awareness.
* 23 new tests pass.
