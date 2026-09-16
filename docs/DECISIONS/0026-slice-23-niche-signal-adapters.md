# ADR-0026 — Slice 23: Niche-Signal Adapters (Search Demand + Amazon Reviews)

**Status:** Accepted
**Date:** 2026-09-15

## Context

CORP's niche-discovery pipeline needs diverse problem-signal sources beyond
Stack Exchange (Slice 22). The design doc identifies two remaining niche-signal
adapters: **search-demand mining** (Google autocomplete as purchase-intent
signal) and **Amazon review mining** (1-3 star reviews as unmet-need signals).
Both are creator-agnostic problem reservoirs — `AdapterFamily.NICHE`.

## Decision

### 1. SearchDemandAdapter

Queries Google's autocomplete endpoint (`suggestqueries.google.com`) to surface
what people are actively searching for in a niche. Two identifier forms:

* bare ``query`` — fetches suggestions for the seed query.
* ``related:query`` — expands with intent modifiers ("best", "how to", "vs",
  "review", "alternative to", "tutorial", "course", "tool for") and deduplicates.

| Property | Value | Rationale |
|---|---|---|
| `AdapterFamily` | `NICHE` | Keyword-keyed, creator-agnostic. |
| `AccessMethod` | `OPEN` | Publicly accessible endpoint, no key needed. |
| `ComplianceStatus` | `COMPLIANT` | Returns aggregate search data, no PII. |
| Content type | `question` | Each suggestion is a demand signal. |

Config: `SEARCHDEMAND_MAX_SUGGESTIONS`, `SEARCHDEMAND_LANGUAGE`, `SEARCHDEMAND_COUNTRY`.

### 2. AmazonReviewAdapter

Collects low-star (1-3) Amazon reviews — direct signals of unmet need and
competitor weakness. Two identifier forms:

* ``asin:B08N5WRWNW`` — reviews for a specific product.
* ``search:keyword`` (or bare text) — searches Amazon for products, then
  collects reviews from the top results.

| Property | Value | Rationale |
|---|---|---|
| `AdapterFamily` | `NICHE` | Product-keyed, creator-agnostic. |
| `AccessMethod` | `OPEN` | Publicly visible review pages. |
| `ComplianceStatus` | `VERIFY` | Amazon's Conditions of Use restrict automated access. |
| Content type | `review` | Each review is a problem/need statement. |
| Star filter | `1,2,3` | Low-star reviews carry the strongest problem signals. |

Config: `AMAZON_MAX_REVIEWS`, `AMAZON_MAX_PRODUCTS`.

### Key design choices

| Choice | Rationale |
|---|---|
| HTML regex parsing for Amazon reviews | Lightweight, no extra dependency. Amazon review pages have stable `data-hook` attributes. |
| `_TextExtractor` (HTMLParser subclass) for stripping tags | Stdlib only; no dependency on BeautifulSoup for this small job. |
| `ComplianceStatus.VERIFY` for Amazon | Amazon ToS restrict scraping; evidence should be compliance-reviewed before production use. |
| `related:` modifier expansion for search demand | Purchase-intent modifiers multiply signal density from a single seed query. |
| Deduplication via `seen` set in `related:` mode | Modifier queries overlap heavily; dedup keeps results clean. |
| Throttle intervals (1s search demand, 3s Amazon) | Conservative defaults to avoid rate limits on both endpoints. |

### Files changed

| File | Change |
|---|---|
| `corp/workers/adapters/searchdemand.py` | New — search demand adapter. |
| `corp/workers/adapters/amazonreviews.py` | New — Amazon review adapter. |
| `corp/workers/adapters/registry.py` | Added both to `KNOWN_PLATFORMS` + `build_adapter`. |
| `corp/config.py` | Added 5 new settings (3 searchdemand, 2 amazon). |
| `.env.example` | Documented the new env vars. |
| `tests/workers/test_searchdemand_adapter.py` | 10 tests. |
| `tests/workers/test_amazonreviews_adapter.py` | 12 tests (including HTML parser unit tests). |

## Consequences

* `NicheDiscoveryCollector` can now accept `platform="searchdemand"` and
  `platform="amazon_reviews"` to mine purchase-intent and unmet-need signals.
* All three niche-signal adapters from the design doc are now implemented
  (Stack Exchange, search demand, Amazon reviews).
* No API keys needed for either adapter — both work out of the box.
* Amazon evidence is tagged `VERIFY` so it can be flagged during compliance
  review before production deployment.
