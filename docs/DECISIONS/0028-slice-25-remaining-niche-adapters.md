# ADR-0028 — Slice 25: Remaining Licensed/Tolerated Niche-Signal Adapters

**Status:** Accepted
**Date:** 2026-09-15

## Context

The design doc's niche-signal family calls for multiple open data sources beyond
Stack Exchange, search demand, Amazon reviews, and marketplace listings (Slices
22–24). Five sources remain from the user's licensed/tolerated data-source list:

1. **Hacker News** (Algolia Search API) — licensed, fully open.
2. **Wikipedia** (Wikimedia Pageviews + Search APIs) — licensed, official.
3. **Google Trends** (Trending Now RSS) — licensed, fully open.
4. **Apple App Store** (review RSS + iTunes Search) — tolerated, open.
5. **pytrends-modern** (interest-over-time via undocumented endpoint) — tolerated.

Additionally, the Etsy leg of the marketplace adapter (Slice 24) used HTML
scraping; the user holds an Etsy Open API v3 Personal App key, so the adapter
should prefer the official API when a key is configured.

Google Play was explicitly excluded ("Leave out Google play if it is illegal
scraping").

## Decision

### New adapters

| Adapter | Platform | Family | AccessMethod | ComplianceStatus | Content types |
|---|---|---|---|---|---|
| `HackerNewsAdapter` | `hackernews` | NICHE | OPEN | COMPLIANT | `story`, `comment` |
| `WikipediaAdapter` | `wikipedia` | NICHE | OFFICIAL | COMPLIANT | `pageview_trend` |
| `GoogleTrendsAdapter` | `googletrends` | NICHE | OPEN | COMPLIANT (RSS) / VERIFY (pytrends) | `trend`, `interest` |
| `AppStoreAdapter` | `appstore` | NICHE | OPEN | COMPLIANT | `review` |

### Key design choices

| Choice | Rationale |
|---|---|
| Hacker News via Algolia `/search` | Fully open, structured JSON, supports stories + comments + Show HN filtering. |
| Wikipedia: search + pageviews combined | Search finds relevant articles; pageviews quantify demand. Single adapter covers both. |
| Google Trends + pytrends in one adapter | RSS feed is the licensed base; pytrends is optional. `_has_pytrends()` checks import, falls back gracefully. |
| pytrends marked VERIFY | Undocumented Google endpoint; widely used but not officially supported. |
| App Store RSS (JSON format) | Apple's JSON-RSS feed is publicly available, no key required. Nested `label`/`attributes` structure handled by dedicated parser. |
| Etsy API v3 upgrade (conditional) | When `ETSY_API_KEY` is set, Etsy uses official Open API v3 (`/v3/application/listings/active`). AccessMethod upgrades to OFFICIAL, ComplianceStatus to COMPLIANT. Falls back to HTML scraping when no key is configured. |

### Files changed

| File | Change |
|---|---|
| `corp/workers/adapters/hackernews.py` | New — HN Algolia adapter. |
| `corp/workers/adapters/wikipedia.py` | New — Wikipedia search + pageviews adapter. |
| `corp/workers/adapters/googletrends.py` | New — Google Trends RSS + optional pytrends adapter. |
| `corp/workers/adapters/appstore.py` | New — Apple App Store review RSS adapter. |
| `corp/workers/adapters/marketplace.py` | Modified — added Etsy Open API v3 path (`_collect_etsy_api`, `_parse_etsy_api_response`), `etsy_api_key` constructor param. |
| `corp/workers/adapters/registry.py` | Added `hackernews`, `wikipedia`, `googletrends`, `appstore` to `KNOWN_PLATFORMS` + `build_adapter`. Updated marketplace block to pass `etsy_api_key`. |
| `corp/config.py` | Added `hackernews_max_items`, `wikipedia_max_articles`, `wikipedia_pageview_days`, `googletrends_max_items`, `googletrends_geo`, `appstore_max_reviews`, `appstore_max_apps`, `appstore_country`, `etsy_api_key`. |
| `.env.example` | Documented all new env vars. |
| `tests/workers/test_hackernews_adapter.py` | 11 tests. |
| `tests/workers/test_wikipedia_adapter.py` | 9 tests. |
| `tests/workers/test_googletrends_adapter.py` | 11 tests. |
| `tests/workers/test_appstore_adapter.py` | 11 tests. |

## Consequences

* The adapter registry now supports 12 platforms total.
* `NicheDiscoveryCollector` can now accept `platform=` for hackernews,
  wikipedia, googletrends, and appstore.
* All licensed data sources from the user's list are now wired in.
* All tolerated sources (autocomplete/searchdemand, App Store RSS, pytrends)
  are wired in with appropriate ComplianceStatus markers.
* The Etsy path is upgraded to official API when a key is available, with
  transparent fallback to HTML scraping.
* 60 tests pass across the 5 adapter test suites in this slice.
