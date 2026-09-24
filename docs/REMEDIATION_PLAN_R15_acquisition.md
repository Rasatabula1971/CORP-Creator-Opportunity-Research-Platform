# R15 — Acquisition reliability remediation plan

**Stage:** 1/2 (intent + research) — **PROPOSED, awaiting Stage 9 gate**
**Date:** 2026-09-22
**Origin:** An external review of the repo (supplied by the user) listing 9
prioritised findings and a proposed "R13" 10-task program. Every claim in
it was independently verified against the code and the live database
before anything was planned here. Several claims did not survive
verification; one proposed fix would have destroyed data.

**Numbering:** the review proposed "R13". That label is already reserved
for the weak-niche "revisit later" state (see
`docs/design/R12_watch_rescan_recollect.md` §3.6), and R14 is the creator
archive (ADR-0064). This work is **R15**.

## 0. The finding that reorders everything

`MultiSourceDiscovery` (`corp/workers/acquisition/multi_discovery.py`) **is
not wired into any live path.** It is referenced only by its own module,
its tests, and a docstring at `niche_discovery.py:26`. The API's discover
job uses `RecursiveNicheDiscovery` (`corp/api/jobs.py:326`); the CLI uses
`NicheDiscoveryCollector` (`corp/workers/run.py:130`). No
`adapter_health.json` has ever been written — `corp_data/` holds only
`warm.db`.

The live acquisition paths are exactly two:

| Path | Entry | Used by |
| --- | --- | --- |
| `RecursiveNicheDiscovery` | `jobs.py:326` | API discover job; **and `watch_rescan.py:429` — the R12 hourly rescanner** |
| `ResearchOrchestrator` | `orchestrator.py:99-107` | creator research chain (console + scheduler) |

Several of the review's findings (health-state lost updates, circuit-breaker
persistence, the `multi_discovery` batch-poisoning bug, its error taxonomy)
are therefore **defects in code that never runs**. They are recorded below
as deferred, not fixed, pending a decision on whether `multi_discovery` is
wired up or deleted.

## 1. Verified findings, ordered by real impact on live code

### R15.1 — Dual-capability adapters fetch everything twice — **HIGH**
`appstore.py:119-123` and `marketplace.py:146-150` each expose two
capability methods that both `return await self.collect(query)`.
`niche_discovery._collect_evidence` builds one task per (adapter,
capability) and runs them under `asyncio.gather` (`_gather_safely`,
`:711-714`). Both tasks hit the same instance; `_throttle_lock` serialises
them, so the second **waits for the throttle interval and then repeats the
identical HTTP work**. Cost: 2× external requests and 2× latency against
Etsy/Gumroad/Udemy and Apple, per keyword, per drill level — now running
unattended every hour via R12. Fix: memoise `collect()` per (instance,
query) for the adapter's lifetime.

### R15.2 — The R12c `is_busy` guard is one-directional — **HIGH (self-inflicted, shipped today)**
`registry_rescan.py:216-225` checks `JobRegistry` before re-researching a
dossier, but **the scheduler never registers itself in `JobRegistry`**
(nothing under `corp/workers/` imports `corp.api.jobs`). So
`routes_ops.py:268`'s 409 does not fire while the scheduler is
re-researching that creator, and a console job runs the full collect loop
against the same creator and the same services concurrently. It is also a
per-dossier check evaluated once, not a tick-level lock. Fix: register the
scheduler's work in the same registry (or a shared claim table) so the
exclusion is mutual.

### R15.3 — YouTube quota accounting does not bound anything — **HIGH**
`youtube.py:128` `self._quota_used = 0` is per-instance, and
`orchestrator.py:100` builds a fresh adapter **per creator account per
run**, so the counter resets continuously; `daily_quota=10000`
(`config.py:15`) is a per-adapter-lifetime ceiling, not a daily one.
Separately, `YouTubeAPIEnricher` (`ecosystem_estimator.py:99-103`) calls
the YouTube API directly, bypassing `YouTubeAdapter._execute` entirely —
**no quota accounting and no rate limiter**. Two code paths spend real
Google quota; one counts, and it keeps forgetting. Fix: process-wide
quota/rate state keyed by service+credential (the `lru_cache(maxsize=1)`
embedder singleton at `jobs.py:183-191` is the established precedent),
and route the enricher through it.

### R15.4 — Evidence dedup key is inconsistent across three sites — **MEDIUM**
| Site | Key | Status |
| --- | --- | --- |
| `niche_discovery.py:684-696` | `(source_platform, source_id, evidence_type)` | correct, **live** |
| `multi_discovery.py:253-262` | `(source_platform, source_id)` | too narrow, dead code |
| `discovery.py:120-129` | `(source_platform, source_id)` | too narrow, CLI only |

The narrow key wrongly suppresses a legitimate second-capability row (one
App Store review is both a `SOLUTION` and a `DISSATISFACTION` observation
by design — `evidence.py:47-49`). Latent today because only the correct
site is live. Fix: make all three use the 3-part key.

**Optional hardening:** `UNIQUE (source_platform, source_id, evidence_type)`
with `ON CONFLICT DO NOTHING` — verified creatable against the live DB
today (**0 conflicts**), and `DO UPDATE` must never be used because the
append-only triggers (`evidence_no_update`, `evidence_no_delete`) forbid it.

**Explicitly rejected:** the review's proposed
`UNIQUE (source_platform, source_id)`. The live DB has **68 conflicting
groups** in 333 rows, so the constraint cannot even be created, and
applying it would destroy half the evidence from every multi-capability
platform. This was the review's headline P1 fix.

### R15.5 — One bad row loses a whole keyword's evidence — **MEDIUM**
`niche_discovery._collect_evidence` adds every row then performs a single
`flush()` at `:680-681` with no savepoint. One bad row (over-length
`source_id`, a NOT-NULL provenance violation) fails the whole batch. This
is milder than the dead code's transaction-poisoning, but it is on the live
path. Fix: savepoint per item (the R8 pattern at `registry_rescan.py:161`),
with `mirror_evidence` kept outside it (`warmstore/sync.py:74` already warns
that mirroring after `flush()` rather than `commit()` can mirror rows
Postgres later rolls back).

### R15.6 — Partial marketplace failure is silent — **MEDIUM**
`marketplace.py:157-178` raises only if **all** marketplaces fail. A
partial failure returns a smaller sample with no signal to the caller, and
`stats.ok()` records the source as successful. Same shape as the
"silent success on empty parse" behaviour in `appstore.py:200-245` and
`wikipedia.py:214-215`, where defensive `.get()` parsing turns schema drift
into zero items recorded as a success.

### R15.7 — No sampling/completeness metadata anywhere — **LOW (honesty, not correctness)**
Verified: marketplace has no pagination at all (`marketplace.py:194-231`);
Etsy's official API path sends one request with `limit=min(limit,25)`;
budget is 30 listings split 10/marketplace (`config.py:48`). Reddit,
YouTube and StackExchange paginate properly. No adapter records
`pages_fetched` / `collection_complete` / `continuation_available`.

**The scoring bias is real but negligible**, and the review's implied
severity is wrong. Marketplace listings are double-filed as `TRANSACTION`
and `SOLUTION`, feeding `solution_saturation = 1 − ln(1+n)/ln(21)`
(weight 0.040) and `purchase_intent = ln(1+n)/ln(16)` (weight 0.080) —
both log-scaled with caps of 20/15, aggregated across every keyword and
run, so normally saturated regardless of truncation. Undersampling moves
the two in **opposite** directions and the conservative one carries double
the weight; worst realistic single-keyword case is **+0.0085** on the
aggregate, net slightly pessimistic. The defect worth fixing is that the
dossier presents these as counts of what *exists*.

### R15.8 — Unguarded nested subscripts on external payloads — **LOW**
`reddit.py:127,190` (`child["data"]`) and `youtube.py:356-358` (four
chained subscripts) versus `appstore.py:207-259` (nine `isinstance`
guards). Real inconsistency. Note the review's broader `metadata:
dict[str, Any]` claim is **overstated**: only 3 unguarded `.metadata`
subscripts exist repo-wide, one is genuine cross-module risk
(`collector.py:74`), and `_EXTRA_KEYS` (`collector.py:64`) whitelists what
reaches the DB.

### R15.9 — Missing `_throttle_lock` in two adapters — **LOW (latent)**
`crowdfunding.py` and `patreon_substack.py` have `_last_request_at` but no
lock. Harmless **today** because each implements exactly one capability, so
the fan-out creates only one concurrent task per instance. Becomes a live
race the moment either gains a second capability. Fix is two lines; do it
as hygiene.

### R15.10 — `ix_evidence_source` does not cover the dedup query — **LOW**
The index is `(source_type, source_id)` (`evidence.py:100`) but the live
dedup filters `(source_platform, source_id, evidence_type)`. Every ingested
item does a non-covered lookup.

## 2. Deferred pending a decision on dead code

`multi_discovery.py` carries a real transaction-poisoning bug (per-item
`except` with no rollback → aborted transaction miscounts every subsequent
item, `stats.ok()` still marks the source successful, and `record_query`
sits outside the try so it propagates and kills the whole run, violating
the module's own "Never raises for individual source failures" docstring),
plus non-atomic health-state writes and no error taxonomy. **None of it
runs.** Decide first: wire it up, or delete it and its health tracker?
Fixing dead code is the worst of the three options.

## 3. Not doing, and why

- **`UNIQUE (source_platform, source_id)`** — destroys the capability
  fan-out; uncreatable against live data (§R15.4).
- **A general shared rate-limit manager as the top priority** — the
  review's "three concurrent jobs → 3×" is a possible state, not a property
  of the system. `JobRegistry` bounds concurrency per creator and per
  campaign; the real exposures are the specific ones in R15.2 and R15.3.
  A shared limiter may follow once those are fixed.
- **Proxy rotation** — agreed with the review: not as an anti-detection
  mechanism. The `COMPLIANT`/`VERIFY`/`TOS_RISK` posture stays.
- **Splitting `NormalizedContent` into discriminated subtypes** — 17
  `content_type` values against a docstring claiming 4 (stale, worth
  updating), but `collector.py:184-197` explicitly detects unhandled types
  and degrades to evidence-only with a log line. No observed defect.
- **Health-state atomic writes / acquisition error taxonomy** — dead code
  (§2).

## 4. Proposed order

R15.2 (my own shipped bug) → R15.1 (live waste, hourly) → R15.3 (real
quota exposure) → R15.5 (live batch loss) → R15.4 (+ optional constraint)
→ R15.6 → R15.9 + R15.10 (hygiene) → R15.8 → R15.7 (needs a product call
on how completeness is surfaced in the dossier).

Each task: build → five gates (`ruff`, `mypy corp --strict`,
`lint-imports`, full `pytest` with no deselects, and `tsc`/`oxlint` if the
frontend is touched) → independent Stage 8 review → Stage 9 gate → ADR.
