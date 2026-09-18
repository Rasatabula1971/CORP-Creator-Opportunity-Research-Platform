# ADR-0032 — CORP1 Stage 5, T2: Wrap Existing Adapters

**Status:** Accepted
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 4 ("How Platforms Map
to Capabilities" table) and Stage 5, task T2

## Context

T1 (ADR-0031) defined the eight capability-provider interfaces. T2 makes the
existing platform adapters implement them, per the CORP1 spec's Phase 1.2
adapter-to-capability mapping table, without rewriting any collection logic.

## Decision

### Ten adapters wired, per the frozen mapping table

Each adapter's class declaration gains the relevant capability interface(s)
as additional base classes; each capability gets one new method that
delegates to the adapter's existing, unmodified `collect()`:

| Adapter | Capabilities added |
| --- | --- |
| YouTubeAdapter | ProblemProvider |
| RedditAdapter | ProblemProvider, DissatisfactionProvider |
| StackExchangeAdapter | ProblemProvider |
| HackerNewsAdapter | ProblemProvider |
| SearchDemandAdapter | SearchIntentProvider |
| AmazonReviewAdapter | DissatisfactionProvider |
| AppStoreAdapter | SolutionProvider, DissatisfactionProvider |
| GoogleTrendsAdapter | TrendProvider |
| MarketplaceAdapter | TransactionProvider, SolutionProvider |
| WikipediaAdapter | TrendProvider (see "Gap found" below) |

Where an adapter implements two capabilities (Reddit, AppStore,
Marketplace), both new methods delegate to the **same** `collect()` call —
the underlying data legitimately serves both lenses (e.g. a Reddit comment
is both a stated problem and, read differently, an expression of
dissatisfaction with existing solutions), matching how T1 designed the
interfaces specifically to support this without a ClassVar collision
(ADR-0031).

### Gap found: Wikipedia was missing from the frozen mapping table

The Phase 1.2 table lists 9 named adapters + "Web Presence (unchanged —
profile enrichment)" — 10 entries. The actual adapters directory has a
`WikipediaAdapter` the table never mentions, even though an earlier ADR
(0029) already counts it among the 8 niche-signal adapters. Its own
docstring says exactly what it is: "a strong demand-validation signal:
articles with sustained high traffic indicate persistent audience
interest" — this is a `TrendProvider`, the same category as Google Trends,
just a different source of the same kind of signal. Assigned accordingly
here, found by reading the adapter's actual code and purpose rather than
by re-deriving the mapping from the frozen table alone.

### Two adapters deliberately left unchanged

- **WebPresenceAdapter** — matches the frozen table's explicit "(unchanged
  — profile enrichment)" note; it enriches a creator's profile, it doesn't
  produce niche evidence.
- **YtDlpAdapter** — not in the frozen table at all, and on inspection not
  a niche-evidence source either: `build_search_adapter()` uses it purely
  for keyword-based **creator discovery** (channel/profile enumeration),
  with audience comments off by default. It plays the same role as Web
  Presence — profile/discovery enrichment, not evidence — so it was left
  out on the same reasoning, not merely by omission.

### No changes to `collect()` anywhere

Confirmed directly, not just claimed: `git diff` against the ten adapter
files shows only class-declaration-line replacements (adding base classes)
and new method insertions. No existing method body changed. This satisfies
T2's frozen boundary exactly.

## Known risk for T3 (flagged by Stage 8 review, not resolved here)

Reddit, AppStore, and Marketplace each implement two capabilities that
delegate to the **same** `collect()` call. If T3 fans a query out across
every capability and calls both `fetch_*` methods on the same adapter
instance for the same query, it gets back two byte-identical
`NormalizedContent` lists — one tagged `evidence_type = PROBLEM`, the other
`DISSATISFACTION` (or the Marketplace/AppStore equivalents). Persisted
naively, this duplicates the same raw content as two separate `Evidence`
rows under two different types, rather than one row legitimately viewed
through two lenses.

T1 already flagged a related but distinct risk (ADR-0031: read
`evidence_type` off the interface class, never the adapter instance). This
is a different failure mode — not *which* type to stamp, but *whether to
store the same content twice at all*. T2's frozen scope was interfaces-only
wiring, not evidence persistence, so this is left for T3 to resolve
deliberately: either dedupe by `(source_platform, external_id)` before
persisting across capability queries against the same adapter instance, or
accept the duplication as an acceptable cost of two-lens evidence and rely
on `NicheCandidateEvidence`/`DossierEvidence` join semantics to avoid
double-counting at the scoring layer. Either is a real design decision,
not a default to fall into silently.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/adapters/{youtube,reddit,stackexchange,hackernews,searchdemand,amazonreviews,appstore,googletrends,marketplace,wikipedia}.py` | Each gains its capability interface base class(es) and one thin delegating method per capability. |
| `tests/workers/test_{youtube,reddit,stackexchange,hackernews,searchdemand,amazonreviews,appstore,googletrends,marketplace,wikipedia}_adapter.py` | Each gains one conformance test proving `isinstance` against its assigned interface(s) and that the delegating method(s) call `collect()` with the given query and return its result unchanged. |

`corp/workers/adapters/web.py` and `corp/workers/adapters/ytdlp.py` are
unmodified — see "Two adapters deliberately left unchanged" above.

## Verification

- `mypy --strict` clean on all ten modified adapter modules (two
  pre-existing, unrelated errors — missing stubs for `googleapiclient` and
  the optional `pytrends` package — confirmed present identically before
  this task via `git stash`, not introduced by it).
- 11 conformance tests pass (`-k test_implements` across the ten adapter
  test files, including the pre-existing `test_implements_source_adapter`
  pattern each was modeled on).
- Full `tests/workers/` suite: **553 passed** (543 baseline + 10 new),
  zero regressions.

## Consequences

- T3 (recursive niche discovery) can now discover which adapters implement
  a given capability via `isinstance(adapter, SomeProvider)` and call its
  named `fetch_*` method — the fan-out mechanism T1 was designed for is
  now backed by real adapters for 7 of the 8 capabilities (all but
  `PlanningIntentProvider` and `MonetisationProvider`, which the CORP1 spec
  assigns to adapters not yet built — Pinterest and Patreon/Substack,
  Phase 2).
- The Wikipedia correction should be reflected back into the frozen Stage
  4/5 doc's adapter mapping, the same way T0's and T1's corrections were,
  so the record stays consistent (see companion doc update).
