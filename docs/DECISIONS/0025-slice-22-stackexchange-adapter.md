# ADR-0025 — Slice 22: Stack Exchange Niche-Signal Adapter

**Status:** Accepted
**Date:** 2026-09-15

## Context

CORP's niche-discovery pipeline needs to surface *audience problems* — the
unmet needs that signal opportunity. Stack Exchange questions ("How do I X?")
are a direct, high-signal source for this. The platform exposes a fully open
REST API (no key required; optional key raises quota from 300 to 10,000
requests/day).

## Decision

Add a `StackExchangeAdapter` in the `NICHE` adapter family that queries the
Stack Exchange API v2.3. It supports two identifier forms:

* `tag:python` / `tag:python;django` — questions by tag, newest first.
* bare text — full-text search via `intitle`.

Questions become `content_type="question"` items; their answers become
`content_type="reply"` items with `parent_id` pointing back to the question.

### Key design choices

| Choice | Rationale |
|---|---|
| `AdapterFamily.NICHE` | Questions represent audience problems, not creator output. |
| `AccessMethod.OFFICIAL` | Uses the documented public API. |
| `ComplianceStatus.COMPLIANT` | API is open; no scraping, no ToS edge cases. |
| Answers fetched in a second pass | Keeps the question pagination loop simple; `/questions/{ids}/answers` batch endpoint handles up to 100 IDs per call. |
| `tenacity` retry with exponential backoff | Handles 429/5xx transients without manual retry loops. |
| Throttle interval (default 1 s) | Well under the 30 req/s anonymous limit; prevents accidental bursts. |
| Quota tracking (`quota_remaining`) | Lets callers monitor usage against the 300/10,000 daily budget. |

### Files changed

| File | Change |
|---|---|
| `corp/workers/adapters/stackexchange.py` | New adapter implementation. |
| `corp/workers/adapters/registry.py` | Added `"stackexchange"` to `KNOWN_PLATFORMS`; wired `build_adapter`. |
| `corp/config.py` | Added `stackexchange_api_key`, `stackexchange_site`, `stackexchange_max_questions`, `stackexchange_include_answers`. |
| `.env.example` | Documented the four new env vars. |
| `tests/workers/test_stackexchange_adapter.py` | 11 tests covering properties, tag/search collection, answers, pagination, empty results, quota, API key, custom site, timestamps. |

## Consequences

* `NicheDiscoveryCollector` can now accept `platform="stackexchange"` to
  discover audience problems from any Stack Exchange site.
* No credentials needed for development or CI; the adapter works out of the
  box with the free 300-request quota.
* Future: tag-trend analysis (question volume over time) can be layered on
  top without changing the adapter interface.
