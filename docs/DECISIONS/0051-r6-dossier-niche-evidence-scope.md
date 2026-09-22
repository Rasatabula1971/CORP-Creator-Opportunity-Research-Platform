# ADR-0051 — R6: Scope dossier demand validation to the niche's own evidence

**Status:** Accepted (Stage 8: ACCEPT, three non-blocking findings applied; Stage 9: accepted by user 2026-09-21)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R6; audit finding #2; spec
dossier layout "Demand Validation" (pp. 30–31)

## Context

`DossierGenerator._build_demand_validation` (added in 71a862b) counted
Evidence whose `research_run_id` belonged to a run with
`ResearchRun.creator_id == creator`. Creator-level research runs only ever
collect PROBLEM evidence (comments, captions); every TREND / SEARCH_INTENT /
TRANSACTION / MONETISATION / DISSATISFACTION row comes from the niche
pipeline, whose runs have `creator_id = NULL`. The section therefore read
all zeros in the normal pipeline. `_filter_niche_opportunities` (ADR-0047)
had the mirror gap: it matched `ResearchRun.niche_id`, which only
`research_more()` sets — the depth-0 drill links its evidence to the
`NicheCandidate` instead — so in the normal pipeline it always fell back to
the global top with a warning.

Separately, `platform_highlights` looked up platform keys (`patreon`,
`substack`, `kickstarter`, `gumroad`, …) that no adapter emits, so those
highlights were permanently 0. (Same class of bug R1 fixed for the type
mapping.)

## Decision

- New `_niche_evidence_clause(niche_id)` — a reusable SQL predicate:
  `Evidence.research_run_id IN (runs WHERE niche_id = :niche)` OR
  `Evidence.id IN (NicheCandidateEvidence for candidates WHERE niche_id =
  :niche AND status IN (PROMOTED, MERGED))`. PROMOTED = the candidate that
  became the niche; MERGED = a candidate folded into it — both are this
  niche's evidence. (The T8 lesson about only trusting PROMOTED applies to
  *lineage/depth*, not to evidence membership.) PROMOTED/MERGED rows from
  earlier generation runs (older `created_at`, possibly `superseded_at`
  set) are included on purpose: evidence is append-only and still real.
- `_build_demand_validation(creator_id, niche_id)`: scope = creator runs ∪
  the niche clause.
- `_filter_niche_opportunities`: uses the niche clause instead of
  `ResearchRun.niche_id` alone.
- `platform_highlights` re-keyed to real `source_platform` strings
  (`crowdfunding`, `patreon_substack`, `marketplace`, `searchdemand`,
  `googletrends`, `amazon_reviews`, `appstore`); `patreon_indicators` /
  `substack_indicators` collapse into `patreon_substack_indicators`.
  `pinterest_activity` is kept, commented as a placeholder for the parked
  T11 adapter (always 0 today). This is a content-shape change to a section
  no frontend code reads yet (R7).

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/dossier/generator.py` | `_niche_evidence_clause`; `_build_demand_validation` takes `niche_id`; `_filter_niche_opportunities` uses the clause; highlights re-keyed |
| `tests/integration/test_dossier_persistence.py` | Two new tests: drill + research_more evidence counted for the right niche only (and a sibling niche's excluded); opportunity backed by candidate-linked evidence is treated as niche-relevant with no fallback warning. Also the first assertions on `audience_analysis`. |

No migration. No model changes.

## Verification

- `ruff check` (E,F,I,N,W) clean on both files; `mypy --strict` clean on
  `generator.py`.
- `tests/integration/test_dossier_persistence.py` +
  `tests/workers/test_dossier_generator.py` +
  `tests/integration/test_registry_rescan.py` +
  `tests/api/test_handoff_endpoint.py`: 43 passed (2 new).
- Full suite, `python -m pytest tests/ -q` with the 7 known pre-existing
  failures deselected: **1259 passed, 1 skipped, 5 deselected** (0 failed).

## Consequences

- Persisted dossiers now carry non-zero demand signals whenever the niche
  pipeline ran; the human gate sees the external-demand evidence the spec
  puts in the Demand Validation section.
- The "using global top" fallback is now the exception (creator with no
  niche-linked evidence at all) rather than the rule.
- R7 (frontend) should type `platform_highlights` with the new key names.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
