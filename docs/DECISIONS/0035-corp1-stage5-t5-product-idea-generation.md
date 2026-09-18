# ADR-0035 — CORP1 Stage 5, T5: Product Idea Generation

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 1 ("Generate product
ideas") and Stage 5, task T5

## Context

T5 takes a creator's active problem clusters (evidence-backed audience
problems, already extracted by the existing clustering pipeline) and asks
an LLM to propose concrete digital products the creator could sell to
their own audience — templates, calculators, courses, trackers, and so
on — grounded in that evidence, never invented independent of it.

## Decision

### Corrected acceptance criterion: no `Evidence.origin` field exists

T5's frozen "Tests" line reads: "provenance test confirming each idea
links back to inference evidence" — worded against `Evidence.origin =
inference`, a field T0 (ADR-0030) deliberately never added. Evidence rows
are raw source data by construction; the observation/inference
distinction this codebase tracks lives per derived artifact instead
(`ProblemObservation.is_inferred`, `NicheCandidate.naming_method`). T5
follows that same convention: `ProductIdea.generation_method` /
`generation_prompt_version` / `generation_model_version` record how the
idea was produced, and the real provenance trail is
`ProductIdeaEvidence` — a join table mirroring `NicheCandidateEvidence`
exactly, linking each idea to the actual `Evidence` rows that grounded it.
`test_provenance_links_to_real_evidence_rows` proves this directly: every
`ProductIdea` has at least one `ProductIdeaEvidence` row whose target
`Evidence.raw_text` genuinely contains the idea's cited grounding term.

### Grounding reuses `niche_naming.check_grounding` unchanged

Same mechanism T3 already uses for niche synthesis: every idea must cite
`evidence_terms` that verifiably appear in the evidence shown to the LLM.
An idea whose terms don't ground, whose `type`/`complexity` don't match
the frozen enum vocabulary, or that's simply missing required fields, is
logged and dropped — never persisted with a fabricated rationale.
`evidence_count >= 1` is a DB `CHECK` constraint (mirroring
`NicheCandidate`'s identical constraint), so an idea genuinely cannot
exist without at least one real evidence link.

### Evidence membership: full-text superset match, deduped by evidence id

Grounding is checked against the (possibly truncated) evidence texts
shown to the LLM, then membership in `ProductIdeaEvidence` is computed
by re-scanning the *full* untruncated `Evidence.raw_text` pool for the
same terms — the same safe-superset pattern T3 uses. Deduped by
`Evidence.id` before linking: two `ProblemObservation` rows in the same
cluster can point at the same underlying `Evidence` row, and
`ProductIdeaEvidence` has a unique `(product_idea_id, evidence_id)`
index — without dedup, a shared evidence row would violate it.

### Rerun supersedes, never deletes

Same latest-wins convention as `CreatorScore`/`OpportunityScore`/
`NicheCandidate`: a new ideation run for a creator supersedes that
creator's still-active `ProductIdea` rows (`superseded_at`); nothing is
ever deleted. `test_rerun_supersedes_previous_ideas` confirms this.

## Files changed

| File | Change |
| --- | --- |
| `corp/core/models/product_idea.py` | New — `ProductIdea`, `ProductIdeaEvidence`, `ProductIdeaType`, `ProductIdeaComplexity`. |
| `corp/core/models/__init__.py` | Registered the new exports (a minor, necessary companion change — every model in this codebase is registered there; not called out separately in T5's frozen file list, same class of small necessary addition as T4's `routes_ops.py` fix, at much lower risk). |
| `migrations/versions/41e47d176102_stage5_t5_product_ideas.py` | New — `product_ideas` + `product_idea_evidence` tables. |
| `rules/product_ideation_prompt.yaml` | New — idea count bounds (3–5), evidence text limits, prompt version. |
| `corp/workers/intelligence/product_ideation.py` | New — `ProductIdeationGenerator`, `propose_ideas`, `IdeationConfig`. |
| `tests/integration/test_product_ideation.py` | New — 8 tests: generation, provenance, three grounding/validation drop cases, rerun supersession, creator-not-found, no-active-clusters. |

## Verification

- `mypy --strict` clean; `ruff check` clean (the two `str, enum.Enum`
  warnings on the new enums match every other enum in this codebase's
  established style — not deviated from for consistency).
- Migration round-tripped (`upgrade` / `downgrade -1` / `upgrade`) cleanly
  against both `corp_test` and the local dev database.
- 8 new tests pass.
- Full `tests/integration/` + `tests/api/` (303 passed, 1 pre-existing
  unrelated skip) and `tests/workers/` (553 tests) suites pass — zero
  regressions.

## Consequences

- T6 (dossier model and generator) can now include product ideas
  alongside problem evidence and scoring in the rendered dossier.
- The frozen Stage 5 T5 card's acceptance-criterion wording should be
  corrected to match (see companion doc update) — the same treatment
  every prior stale reference has received (T0, T2, T3).
