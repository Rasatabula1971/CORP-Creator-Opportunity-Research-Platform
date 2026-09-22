# ADR-0053 — R5: Depth cap on research_more, full fan-out, registry clock at promotion, EXCLUDED lifecycle

**Status:** Accepted (Stage 8: round 1 REVISE with two blocking findings fixed, round 2 ACCEPT; Stage 9: accepted by user 2026-09-21)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R5; audit findings #6, #9, #10, #11

## Context

Four small gaps in the niche pipeline, all in one file cluster:

1. **Depth cap bypass (#6).** `research_more()` enters `_drill` at
   `parent.depth + 1` with no guard; `_handle_niche` persists whatever depth
   it receives. A niche already at depth 3 produced depth-4 candidates,
   breaking the spec's "hard-capped at depth 3". The cap only stopped
   *recursion*, not entry.
2. **Fan-out omitted two NICHE-family adapters (#9).** `crowdfunding` (T13,
   TransactionProvider) and `patreon_substack` (T14, MonetisationProvider)
   were registered but not in `NICHE_FAN_OUT_PLATFORMS`, so the drill never
   collected Kickstarter/Indiegogo TRANSACTION or Patreon/Substack
   MONETISATION evidence and the scoring engine's purchase-intent and
   monetisation dimensions saw nothing from them.
3. **Registry clock only set at verification (#11).** Promoted-but-unverified
   niches kept `next_recheck_at = NULL`, which `_is_registry_fresh` treats as
   "due", so the registry never protected them from re-drilling. Spec:
   "always set on scan completion".
4. **`NicheLifecycleStatus.EXCLUDED` never set (#10).** Exclusion matches
   only marked the *candidate* REJECTED (ADR-0033's resolution). The frozen
   enum value on `Niche` — which the spec's "Un-excluding a niche — HUMAN"
   action needs — stayed dead.

## Decision

- `_drill`: first check is `depth > max_depth` → log, `stats.skip()`,
  `stats.extra["skipped_max_depth"] += 1`, return. Placed in `_drill`
  rather than `research_more` so both entry points share one guard.
  Failure mode is a completed run with the skip recorded, not an
  exception: `research_more` runs as a background job behind the dossier
  decision gate, and a raised error would only turn into a failed job.
- `NICHE_FAN_OUT_PLATFORMS` += `crowdfunding`, `patreon_substack`.
- `CanonConfig.recheck_days` (default 90); on promotion the new `Niche`
  gets `last_researched_at = now`, `next_recheck_at = now + recheck_days`.
  Both call sites (`corp/api/jobs.py` canonicalize job, `corp/workers/run.py`
  CLI) pass the value from `rules/niche_discovery_prompt.yaml` via
  `DiscoveryConfig.from_rules(...).recheck_days` — the same source T3 and
  the T10 scheduler already read. `VerifyConfig.recheck_days` replaces the
  literal 90 in `niche_verification.py` for the same reason (default
  unchanged; CLI/job wiring for verification left as-is).
- `_mark_niche_excluded(label)`: on an exclusion match (keyword in `_drill`,
  or a synthesized niche in `_handle_niche`), if a `Niche` already exists
  under that label (canonical name first, alias as fallback — the two are
  unique only within their own tables), set `lifecycle_status = EXCLUDED`.
  Candidates are still REJECTED as before; the niche-level status is
  additive. Un-excluding remains a human action (no code path clears
  EXCLUDED).
- **Stage 8 revise round.** (1) In `_drill` the exclusion check now runs
  *before* the registry-freshness check: every promoted niche carries a
  recheck clock after this task, so the old order would have hidden an
  excluded keyword behind "still fresh" for `recheck_days`. (2)
  `creator_onboarding.py::_selected_niches` adds
  `Niche.lifecycle_status != EXCLUDED` — a niche excluded after being
  SELECTED in a campaign must not onboard creators (the API's niche
  listing in `routes.py` still shows it, which is correct: the human needs
  to see it to un-exclude). This touches one file outside R5's planned
  list; the alternative (softening the ADR's claim) would have left the
  vision's policy gate open. (3) The niche-level mark in `_handle_niche`
  requires a NAME match; candidate rejection still matches
  name+description, but an LLM-written description alone cannot flip a
  pre-existing canonical niche whose reversal is human-only.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/intelligence/niche_discovery.py` | Depth guard in `_drill`; two fan-out platforms; `_mark_niche_excluded` + two call sites; `NicheLifecycleStatus` import |
| `corp/workers/intelligence/niche_canonicalization.py` | `CanonConfig.recheck_days`; clock set on promotion |
| `corp/workers/intelligence/niche_verification.py` | `VerifyConfig.recheck_days` replaces literal 90 |
| `corp/api/jobs.py`, `corp/workers/run.py` | Pass `recheck_days` from the rules file |
| `corp/workers/acquisition/creator_onboarding.py` | `_selected_niches` skips EXCLUDED niches (revise round) |
| `tests/integration/test_creator_onboarding.py` | EXCLUDED-but-SELECTED niche onboards no creators |
| `tests/integration/test_niche_discovery.py` | Six tests: fan-out constant; `research_more` at max depth persists nothing and records the skip; excluded synthesized niche marks an existing niche EXCLUDED; excluded keyword marks a niche EXCLUDED via alias without collecting; exclusion beats registry freshness; description-only match rejects the candidate but leaves the niche |
| `tests/integration/test_niche_canonicalization.py` | Promotion starts the recheck clock with the configured interval |

No migration. No model changes.

## Verification

- `ruff check` (E,F,I,N,W) clean on all changed files; `mypy --strict`
  clean on the five changed source files.
- `tests/integration/test_niche_discovery.py` +
  `test_niche_canonicalization.py` + `test_niche_verification.py` +
  `test_registry_rescan.py` + `test_creator_onboarding.py`:
  68 passed (8 new across the two rounds).
- Full suite, `python -m pytest tests/ -q` with the 7 known pre-existing
  failures deselected, re-run after the revise round: **1272 passed,
  1 skipped, 5 deselected** (0 failed; first round was 1269 / 0).

## Consequences

- No candidate can exist beyond `max_depth` via any entry point.
- Drill evidence now includes crowdfunding and Patreon/Substack rows, so
  `demand_validation` (R6) and the T7/T21 purchase-intent/monetisation
  scores receive real input.
- Every promoted niche has a recheck clock; `_is_registry_fresh` now
  protects it for `recheck_days`. Verification re-stamps the clock on pass
  (unchanged behaviour).
- Existing niches whose NAME matches an exclusion rule are moved to
  EXCLUDED the next time a drill encounters that keyword or synthesizes
  that name, regardless of registry freshness; there is no batch backfill
  (an EXCLUDED status set without a human in the loop was judged riskier
  than leaving pre-existing rows for the next scan to catch). Creator
  onboarding then skips them even if they were already SELECTED.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
