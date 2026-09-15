# Slice 10 — Niche Verification

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, §7

## What shipped

Candidate niches are verified against evidence-quality thresholds and advanced
to ACTIVE when they pass. The verification is deterministic — no LLM, no
embedding — just min-evidence, min-author, and a broad-domain gate.

- `corp/workers/intelligence/niche_verification.py` — `NicheVerifier`:
  loads PROMOTED, non-superseded candidates for a campaign (ordered by
  evidence count descending), checks each against configurable thresholds:
  - `min_evidence` (default 5): candidate must have ≥ N evidence items.
  - `min_authors` (default 3): candidate must have ≥ N distinct authors.
  - `reject_broad_domain` (default True): `is_broad_domain=True` fails.

  On pass: `Niche.lifecycle_status` → ACTIVE, `last_researched_at` stamped,
  `CampaignNiche.status` → VERIFIED.

  On fail: niche stays at CANDIDATE, `CampaignNiche.status` → DISCOVERED
  with a rationale string explaining why.

  Already-active niches are skipped (niche.lifecycle_status != CANDIDATE).

- CLI: `verify <campaign_id> [--min-evidence N] [--min-authors N] [--allow-broad]`.

Reuse, not rebuild: `Niche`, `CampaignNiche`, `NicheCandidate` (Slice 8),
`start_run`/`finish_run`, no migration needed.

## Acceptance criteria → how each is met

- **Niches meeting thresholds advance to ACTIVE.**
  `test_niche_passes_verification` (10 evidence, 5 authors → ACTIVE, VERIFIED).
- **Niches below thresholds stay CANDIDATE with rationale.**
  `test_niche_fails_low_evidence`, `test_niche_fails_low_authors`,
  `test_broad_domain_rejected` — each fails with a specific reason string.
- **Broad-domain gate is configurable.**
  `test_broad_domain_allowed` (reject_broad_domain=False → passes).
- **Already-active niches are skipped.**
  `test_already_active_niche_is_skipped` — niche at ACTIVE is not rechecked.
- **Empty campaigns complete cleanly.**
  `test_empty_campaign_completes` — 0 candidates checked, status=completed.
- **Mixed pass/fail in one campaign.**
  `test_multiple_niches_mixed_results` — one passes, one fails.

## Verification

- `tests/integration/test_niche_verification.py` (8, real Postgres): all
  threshold paths, broad-domain gate, skip logic, empty campaign, mixed results.
- Non-DB suite: 304 passed. DB suite: 8 passed. ruff: clean.
- **Live** (dev DB, campaign "Slice 7 live demo"):
  - `verify ce2d59c9-cc13-48fe-bb44-6a13213a1a28` → 3 checked, 3 verified,
    0 failed.
  - **Home Espresso Machine Repair** (23 evidence, 18 authors) → PASS → ACTIVE
  - **Reef Aquarium Nitrates** (10 evidence, 6 authors) → PASS → ACTIVE
  - **Sim Racing Hardware Setup** (7 evidence, 7 authors) → PASS → ACTIVE
  - All three CampaignNiche rows updated to VERIFIED.

## Assumptions and open items

- Default thresholds (5 evidence, 3 authors) are conservative for the current
  dataset where all candidates comfortably exceed them. Tunable via CLI.
- A niche that fails verification stays at CANDIDATE indefinitely. A future
  slice could add a REJECTED lifecycle status or time-based expiry.
- Verification does not re-count evidence directly; it trusts the
  `evidence_count` and `author_count` on the NicheCandidate row set during
  Slice 8 candidate generation.
