# Slice 12 — Niche Qualification Scoring

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

Deterministic, YAML-driven qualification scoring for verified niches. For each
VERIFIED CampaignNiche in a campaign, computes `qualification_score`,
`confidence`, and `research_completeness` from evidence depth, author diversity,
ecosystem size, target-band density, and specificity. No LLM, no API key, no
cost.

- `rules/niche_qualification.yaml` — weights (sum to 1.0), normalizer caps,
  confidence thresholds, and completeness stage definitions.

- `corp/core/scoring/niche_qualification.py` — pure scoring functions (no DB,
  no I/O): `NicheInput` dataclass, five component scorers (log-scaled evidence
  depth, log-scaled author diversity, log-scaled ecosystem size, target band
  ratio, specificity flag), `compute_qualification_score` (weighted average),
  `compute_confidence` (three bands: high/medium/low based on evidence/author
  thresholds and ecosystem availability), `compute_research_completeness`
  (fraction of 4 stages completed).

- `corp/workers/intelligence/niche_qualification.py` — `NicheQualifier`
  pipeline: loads VERIFIED CampaignNiche rows, resolves the promoted
  NicheCandidate for evidence/author counts, calls the scorer, persists results.

- `RunType.NICHE_QUALIFICATION` added to the enum in
  `corp/core/models/workflow.py`. No migration needed — `run_type` is stored as
  `String(30)`.

- CLI: `qualify <campaign_id> [--rules PATH]`.

## Acceptance criteria and how each is met

- **Qualification score is computed per niche.**
  `test_scores_single_niche` (score, confidence, completeness all populated).
- **High evidence yields high confidence.**
  `test_high_evidence_gets_high_confidence` (30 evidence/15 authors + ecosystem → 1.0).
- **Low evidence yields low confidence.**
  `test_low_evidence_gets_low_confidence` (2 evidence/1 author, no ecosystem → ≤ 0.3).
- **Broad domains are penalised.**
  `test_broad_domain_penalised` (specific score > broad score, same evidence).
- **Ecosystem data boosts score.**
  `test_ecosystem_boosts_score` (with ecosystem > without, same evidence).
- **Research completeness tracks pipeline stages.**
  `test_research_completeness_stages` (full=1.0, no ecosystem=0.5).
- **Empty campaign completes cleanly.**
  `test_empty_campaign`.
- **Non-verified niches are skipped.**
  `test_skips_non_verified`.
- **Missing candidate still scores (with zero evidence).**
  `test_no_candidate_still_scores`.
- **Scoring is deterministic.**
  `test_deterministic_scoring` (two runs, same input → same score).

## Verification

- `tests/integration/test_niche_qualification.py` (10, real Postgres): all
  scoring paths, confidence bands, completeness, empty/skip cases,
  determinism.
- Non-DB suite: 304 passed. DB suite: 10 passed. ruff: clean (pre-existing
  UP042 only).
- **Live** (dev DB, campaign "Slice 7 live demo"):
  - **Sim Racing Hardware Setup**: score=0.4855, confidence=0.60, completeness=0.75
  - **Reef Aquarium Nitrates**: score=0.5122, confidence=0.60, completeness=0.75
  - **Home Espresso Machine Repair**: score=0.6260, confidence=1.00, completeness=0.75
  - Home Espresso ranks highest due to 23 evidence / 18 authors (vs 7-10 for
    the others). Completeness is 0.75 across the board because
    `target_band_creator_count` is 0 (no YouTube API enrichment ran). This is
    correct behavior — completeness reflects actual pipeline progress.

## Assumptions and open items

- The scoring formula uses log-scaled normalizers capped at configurable
  thresholds (evidence 50, authors 30, ecosystem 50) so diminishing returns
  are built in. All weights are reconfigurable via YAML without code changes.
- Confidence is a stepped function (0.2/0.3/0.5/0.6/1.0) based on evidence
  and ecosystem availability. A future slice could replace this with a
  continuous function.
- Research completeness counts 4 boolean stages: has_evidence, is_verified,
  has_ecosystem_data, has_target_band_data. New pipeline stages can be added
  to the YAML list.
