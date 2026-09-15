# ADR-0027 — Slice 24: Marketplace Listings Adapter (Gumroad / Etsy / Udemy)

**Status:** Accepted
**Date:** 2026-09-15

## Context

The design doc's niche-signal family includes "Marketplace listings + reviews
(what already sells)" — Gumroad, Etsy, and Udemy for §8 saturation + pricing
validation. With Stack Exchange (Slice 22), search demand, and Amazon reviews
(Slice 23) done, this is the last niche-signal adapter.

Product listings tell CORP what already sells in a niche: how many competing
products exist (saturation), at what price points (pricing validation), and
how well-received they are (rating/review signals).

## Decision

Add a `MarketplaceAdapter` that queries three digital marketplaces:

* **Gumroad** — HTML scraping of `/discover` search results.
* **Etsy** — HTML scraping of `/search` results.
* **Udemy** — JSON API (`/api-2.0/courses`) for structured course data.

Identifier forms:

* `gumroad:keyword` / `etsy:keyword` / `udemy:keyword` — single marketplace.
* bare `keyword` — searches all configured marketplaces, distributing
  `max_listings` evenly.

Each listing becomes a `listing` content item with pricing, rating, review
count, and marketplace name in metadata.

### Key design choices

| Choice | Rationale |
|---|---|
| `AdapterFamily.NICHE` | Keyword-keyed, creator-agnostic saturation signal. |
| `AccessMethod.OPEN` | All three expose public product pages / API. |
| `ComplianceStatus.VERIFY` | Marketplace ToS may restrict automated access. |
| Udemy via JSON API | Udemy's `/api-2.0/courses` is a public endpoint that returns structured data — no HTML parsing needed. |
| Gumroad/Etsy via HTML regex | Lightweight, no BeautifulSoup dependency. Both have stable CSS class patterns. |
| Configurable marketplace list | `MARKETPLACE_SITES` lets operators skip marketplaces that block their IP or change layout. |
| Per-marketplace HTML parsers | Each marketplace has its own page structure; separate parsers keep the code testable. |

### Files changed

| File | Change |
|---|---|
| `corp/workers/adapters/marketplace.py` | New — marketplace adapter with three parsers. |
| `corp/workers/adapters/registry.py` | Added `"marketplace"` to `KNOWN_PLATFORMS` + `build_adapter`. |
| `corp/config.py` | Added `marketplace_max_listings`, `marketplace_sites`. |
| `.env.example` | Documented the new env vars. |
| `tests/workers/test_marketplace_adapter.py` | 17 tests covering properties, helpers, per-marketplace parsing, collect modes, caps, empty results. |

## Consequences

* `NicheDiscoveryCollector` can now accept `platform="marketplace"` to
  discover saturation and pricing signals across Gumroad, Etsy, and Udemy.
* The entire niche-signal adapter family from the design doc is now complete:
  Stack Exchange, search demand, Amazon reviews, and marketplace listings.
* The adapter registry now supports 8 platforms total.
* Marketplace evidence is tagged `VERIFY` — operators should confirm
  compliance posture before production use.
