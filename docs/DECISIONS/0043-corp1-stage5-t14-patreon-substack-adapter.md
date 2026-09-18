# ADR-0043 — CORP1 Stage 5, T14: Patreon + Substack Adapter (Phase 2.4)

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Phase 2.4 "Patreon and
Substack Adapter" and Stage 5, T11–T15 ("Phase 2 adapters" template)

## Context

Same shared adapter-task template as T11–T13: one new file under
`corp/workers/adapters/`, no changes to any other adapter or the
scoring engine, no migration, a conformance test plus a "live-fixture
test" for the evidence fields named.

Phase 2.4: capability `MonetisationProvider`. "Why it matters": "If
people already pay creators in a niche for content, that niche has
proven monetisation potential. A creator with Patreon supporters has an
audience willing to spend money." Collects: creator pages in the niche,
tier structures and pricing, patron and subscriber counts where
visible, content themes and offerings, community activity signals.

**Applying the standing practice (verify live before writing code,
per memory — see T11/T12/T13):** Substack was checked live and
confirmed real and rich. **Patreon could not be checked**:
patreon.com is blocked by this session's built-in browser's own
safety restrictions ("not allowed due to safety restrictions"), and
Claude in Chrome (the fallback, the user's real browser) was not
connected when this task was built. Presented to the user directly
rather than guessing anyway or blocking the whole task on it; the user
had no preference among the options offered, so the lowest-friction,
most-precedented path was taken: ship Substack fully verified now,
disclose Patreon as an explicit, undone gap rather than build it on an
unverified assumption (the T11/T12 mistake this practice exists to
prevent).

## Decisions

### Substack: `GET /api/v1/top/search`

Confirmed live: `?query=<query>&fromSuggestedSearch=false` — fully
unauthenticated (other Substack API calls on the same page returned
401; this one returned 200 without a session). Returns mixed-type
search hits (`"post"`, `"comment"`, `"profileSearchResults"`); `"post"`
hits carry a nested `publication` object with real creator data:
`name`, `hero_text`/`author_bio`, `author_name`, `freeSubscriberCount`,
`payments_state`, `plans` (when payments are enabled — confirmed by
fetching a paid publication directly: real Stripe Plan objects,
`amount` in cents/`currency`/`interval`/`nickname`), and `sections`
(named content categories). The same publication can appear under
multiple post hits for one query — `_parse_substack_response`
de-duplicates by publication id before emitting one item per creator
page.

**Two disclosed data gaps, matching real API behavior, not guessed
around:**
- **`freeSubscriberCount` is a free-subscriber count, not a patron/
  paid-subscriber count.** Substack's public search API never exposes
  paid-subscriber numbers (private business data). Stored as
  `metadata["free_subscriber_count"]`, explicitly documented as an
  audience-size proxy only — the actual monetisation signal is
  `payments_enabled` + the `tiers` pricing list, not this count.
- **No aggregate community/engagement count exists in this response.**
  `community_enabled`/`has_recommendations` (booleans from the
  publication object) are stored as coarse proxies, not a number.

### Patreon: intentionally not implemented, not stubbed with a guess

`PatreonSubstackAdapter._collect_from` recognizes the `patreon:`
prefix and lists `"patreon"` in `PLATFORMS` (so a caller's request
routes correctly, not silently misrouted to "unknown platform"), but
returns an empty list with a logged warning rather than fabricated
results — no HTTP call is ever attempted. A bare-query fan-out
(`_collect_all`) therefore only ever yields real results from Substack;
Patreon's contribution is always zero, by design, until it can be
verified. Because Patreon never *raises* (it succeeds trivially with
nothing), a Substack failure alone does not trigger the "all platforms
failed" `RuntimeError` inherited from `CrowdfundingAdapter`'s pattern —
verified directly with a test (`test_substack_failure_returns_empty_
not_raises`).

### One adapter, umbrella platform name — mirrors `CrowdfundingAdapter`

`PatreonSubstackAdapter(SourceAdapter, MonetisationProvider)` follows
the same established multi-platform-in-one-file pattern T13 used:
`platform`/`source_platform` = `"patreon_substack"` (not per-site),
`metadata["platform"]` distinguishing the site, `substack:`/`patreon:`
identifier prefixes plus bare-query fan-out, per-platform failure
isolation copied from `CrowdfundingAdapter._collect_all` unchanged in
structure.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/adapters/patreon_substack.py` (new) | `PatreonSubstackAdapter`, `_parse_substack_response()`, `_extract_tiers()`, `_section_names()`, `_substack_url()`, `_parse_substack_date()`. |
| `corp/workers/adapters/registry.py` | New `if name == "patreon_substack":` branch; `"patreon_substack"` added to `KNOWN_PLATFORMS`. |
| `corp/config.py` | New `patreon_substack_max_creators` setting. |
| `tests/workers/test_patreon_substack_adapter.py` (new) | 21 tests: adapter properties, Substack response parsing (dedup, free vs. paid publication fields, skip-empty), tier/section/url/date helper functions, `collect()` via mocked HTTP for the substack prefix and bare-query fan-out, Patreon-prefix graceful no-op, Substack-failure-doesn't-raise, max-creators cap, request counting, `close()`, one conformance test for `MonetisationProvider`. |

No changes to any other adapter file or to `rules/scoring.yaml`.

## Stage 8 review: ACCEPT, no required changes

Independent review confirmed the central judgment call — shipping
Substack-only rather than pausing the whole task like T11/T12 — was
the right distinction to draw: T11/T12 were paused over *epistemic*
risk (would have had to guess a field shape), while here nothing is
guessed; Patreon is simply not queried at all, with the code fully
explicit and inert about it (no HTTP call attempted, a clear warning
logged). Verified directly against the code, not assumed: no path
anywhere mislabels `free_subscriber_count` as a patron/paid count, and
the `_collect_all`/Patreon-no-op RuntimeError-suppression interaction
works exactly as described. One soft note, not a required change: the
ADR could have more explicitly weighed "pause and wait for the Chrome
extension to connect" as a third option before defaulting to
ship-partial. All tool/test runs matched exactly.

## Verification

- `mypy --strict` and `ruff check` clean on `patreon_substack.py`, the registry/config companion changes, and the test file.
- `python -c "build_adapter('patreon_substack')"` confirmed live: returns a `PatreonSubstackAdapter` with `family=NICHE`, `access_method=OPEN`, `compliance_status=VERIFY`.
- `tests/workers/test_patreon_substack_adapter.py`: 21 passed.
- Full `tests/workers/`: 612 passed (up from 591, the 21 new tests), zero failures.
- Full `tests/integration/` + `tests/api/`: 346 passed, 1 pre-existing
  unrelated skip — unchanged from baseline, confirming the
  registry/config companion changes introduced zero regressions.

## Consequences

- A follow-up task can add real Patreon support once its data can be
  verified live (the user's own Chrome connecting, or a manual check) —
  additive to this file's existing structure, not a rework.
- T15 (Quora — the last of the Phase 2 adapters) should apply the same
  live-verification practice before writing any code, and treat any
  further "can't verify this source" case the same way this task did:
  ship what's verified, disclose what isn't, ask rather than guess.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF, none of which T14 touched — the same pre-existing
dev-environment changes disclosed in every ADR since T4. Not staged as
part of this task's commit.
