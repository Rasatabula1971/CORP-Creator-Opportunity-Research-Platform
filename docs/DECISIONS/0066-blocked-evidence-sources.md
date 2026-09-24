# ADR-0066 — Sources that refuse automated access: Udemy, Etsy, Kickstarter, Indiegogo

**Status:** Accepted
**Date:** 2026-09-24
**Context:** first unattended discovery pass on the laptop after ADR-0065
restored the source-health breaker onto the live engine.

## What happened

The first real pass logged `403 Forbidden` from four sources on every
keyword: Kickstarter and Indiegogo (`CrowdfundingAdapter`), Etsy and Udemy
(`MarketplaceAdapter`). The breaker did its job (each source is now skipped
after `health_disconnect_after` consecutive failures and probed once per
cooldown), but "skipped after failing" is the wrong state for a source that
can never answer: it still costs one blocked request per keyword on every
probe, and the run stats read like an outage rather than a decision.

## What was checked

- The same four endpoints were requested from the laptop (no VPN) with a
  Chrome user agent and browser `Accept` headers. Etsy, Udemy and Indiegogo
  answered 403; Kickstarter did not complete a response at all. So the
  blocks are not about our headers, and a header change would not help.
- **Udemy**: the endpoint the adapter uses, `api-2.0/courses`, is the
  Affiliate API. Udemy discontinued that API on 2025-01-01. Permanent.
- **Etsy**: the search page is behind DataDome, which returns a hard 403 to
  any non-browser client and refuses datacentre addresses outright. Etsy
  publishes an Open API v3 (`listings/active`) with a free personal-app
  key, and `MarketplaceAdapter` already uses it when `ETSY_API_KEY` is set,
  tagging the rows `COMPLIANT` rather than `VERIFY`.
- **Kickstarter**: no public API programme exists; `discover/advanced.json`
  is the site's own client endpoint behind Cloudflare bot management.
  ADR-0042 rated it `VERIFY` for exactly this reason.
- **Indiegogo**: `api/projectSearch/searchProjects` is likewise an internal
  endpoint behind a managed edge challenge. Indiegogo does publish a
  "Public API" help article (registration required); whether it offers
  project search was not confirmed from the sandbox and is an open item.

## Decision

1. **Udemy is removed from the default `MARKETPLACE_SITES`**, and the
   registry drops it with a warning if it is still listed. Dead endpoint.
2. **Etsy is used only through the official API, and is off by default.**
   The official Etsy Open API requires an approved developer app, which is
   not currently available to this operator, so `etsy` was removed from the
   default `MARKETPLACE_SITES` (now `gumroad` only). Without `ETSY_API_KEY`
   the registry still leaves Etsy out (with a warning naming the variable)
   rather than scraping into DataDome; add `etsy` back to `MARKETPLACE_SITES`
   only once a key is obtained. With a key, rows are tagged `COMPLIANT`.
3. **The crowdfunding source is off by default** via a new setting,
   `DISCOVERY_DISABLED_SOURCES` (default `crowdfunding`). A disabled
   platform is recorded in `run.stats.extra.skipped_sources` as
   `disabled by DISCOVERY_DISABLED_SOURCES`, is never built, and never
   touches source health. The adapter and its tests stay, for when an
   official route is found.
4. **A registry `AdapterConfigError` at fan-out time is a skip, not a
   health failure** (`not configured; details in the server log`), so a
   marketplace list with nothing usable left does not trip the breaker.

Not done, and why:

- Headless browsers, paid scraping services or fingerprint spoofing to get
  past DataDome/Cloudflare. Every evidence row carries a compliance tag and
  the product's posture is `COMPLIANT`/`VERIFY`/`TOS_RISK`, not evasion.
- Deleting the crowdfunding adapter. Purchase-intent evidence from backers
  is the strongest signal the spec names; the code is kept behind the
  switch until an official source exists.

## Consequences

- Four fewer guaranteed-403 requests per keyword per drill.
- `TRANSACTION` and `SOLUTION` evidence is thinner than the scoring rules
  assumed when the crowdfunding and marketplace adapters were written.
  `solution_saturation` and `purchase_intent` (both log-scaled, low weight)
  lean on Etsy via the API, Gumroad, and App Store data until Indiegogo's
  official API is evaluated.
- Operators see the reason per source in the run's `skipped_sources`, not a
  breaker state that looks like an outage.

## Follow-ups

- Evaluate Indiegogo's Public API (registration, search support, terms).
- Etsy developer-app approval was not granted, so Etsy stays out of the
  default marketplace list. Revisit `ETSY_API_KEY` if an approved app is
  obtained later.
- The stale `niche_discovery_platforms` setting (its consumer was deleted
  in ADR-0065) can go in a later hygiene pass.
