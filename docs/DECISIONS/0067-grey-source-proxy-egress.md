# ADR-0067 — Grey-source adapters egress through an optional proxy

**Status:** Accepted
**Date:** 2026-09-26

## Context

CORP runs on the operator's laptop, so every adapter's requests leave from
the operator's home connection. For official-API and honest-UA sources
(YouTube Data API, Reddit JSON, Stack Exchange, Hacker News, Wikipedia,
the creator-web adapter) that is fine: the access is sanctioned and
identified.

Three adapters are different. `amazon_reviews`, `marketplace` (Gumroad
HTML) and `crowdfunding` read pages that have no official API, send a
browser user agent, and are tagged `VERIFY`. If one of those sites blocks
CORP, the block lands on the home address — and with it the operator's
own browsing of the same sites. The operator's stance is to keep using
these sources until they are blocked, so the block should cost a
replaceable address, not a personal one. No adapter uses a login or
cookie, so no personal account is exposed; this ADR keeps it that way.

## Decision

1. New settings: `GREY_PROXY_URL`, `GREY_PROXY_REQUIRED` (default
   `false`), `GREY_PROXY_PLATFORMS` (default
   `amazon_reviews,marketplace,crowdfunding`).
2. The registry passes the proxy to exactly the listed platforms; their
   `httpx.AsyncClient` is built with `proxy=`. Every other adapter stays
   direct.
3. With `GREY_PROXY_REQUIRED=true` and no URL, the grey adapters raise
   `AdapterConfigError` instead of falling back to the home address. The
   existing source-health handling treats that like any other
   unconfigured source.
4. The proxy URL is logged only with credentials stripped
   (`redact_proxy`).

## Consequences

- Default behaviour is unchanged (no proxy, direct).
- SOCKS proxies need the `httpx[socks]` extra; HTTP(S) proxies need
  nothing extra.
- Future stealth/browser adapters (e.g. Scrapling) must be added to
  `GREY_PROXY_PLATFORMS` and must never carry a login or cookie belonging
  to the operator.
- A proxy changes where a block lands, not whether the access is
  permitted; the `VERIFY` compliance tag and lower evidence trust stay.
