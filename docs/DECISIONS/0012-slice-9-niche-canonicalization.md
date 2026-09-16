# Slice 9 — Niche Canonicalization & Deduplication

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, §12 / §7

## What shipped

Staged NicheCandidate rows can be promoted to canonical Niche rows or merged
into existing niches when a near-duplicate is detected. No migration needed —
all tables already exist from earlier slices.

- `corp/workers/intelligence/niche_canonicalization.py` — `NicheCanonicalizer`:
  loads staged, non-superseded candidates for a campaign (ordered by evidence
  count descending so the most-evidenced candidate wins), deduplicates against
  all existing niches, and either promotes or merges each one.

  Deduplication strategy (no LLM required):
  1. **Exact name match** (case-insensitive): candidate label matches an
     existing `Niche.canonical_name` → merge.
  2. **Alias match** (case-insensitive): candidate label matches an existing
     `NicheAlias.alias` → merge into the alias's niche.
  3. **Embedding similarity**: embed the candidate label with the same
     sentence-transformer, compare against all existing niche labels via cosine
     similarity; score ≥ threshold (default 0.82) → merge.
  4. **No match**: promote to a new Niche row with `lifecycle_status=CANDIDATE`.

  On merge: candidate status → MERGED, `niche_id` set, the candidate's label
  is added as a `NicheAlias` (unless it matches the canonical name exactly,
  case-insensitive, to avoid redundant aliases).

  On promote: new `Niche` row created, candidate status → PROMOTED, `niche_id`
  set; the new niche immediately enters the embedding comparison pool for
  subsequent candidates in the same batch.

  Both actions create a `CampaignNiche` row linking the niche to the campaign
  (skipped if the pair already exists, so reruns are safe).

- CLI: `canonicalize <campaign_id> [--similarity-threshold N]`.

Reuse, not rebuild: `Niche`, `NicheAlias`, `CampaignNiche`, `start_run` /
`finish_run`, `embed_texts`, NicheCandidate (Slice 8).

## Acceptance criteria → how each is met

- **Staged candidates become canonical niches or merge into existing ones.**
  `test_promotes_all_unique_candidates` (3 distinct → 3 promoted),
  `test_merges_exact_name_match_same_case` (case-insensitive merge),
  `test_merges_via_alias_match` (alias-based merge),
  `test_merges_by_embedding_similarity` (cosine merge, lower-evidence merged).
- **No redundant aliases.** `test_no_duplicate_alias_when_label_is_canonical` —
  when the merged label matches the canonical name, no alias is created.
- **CampaignNiche links are idempotent.** `test_campaign_niche_not_duplicated`
  — a second canonicalize run creates 0 new CampaignNiche rows.
- **Only STAGED non-superseded candidates are processed.** Two tests confirm
  REJECTED and superseded candidates are skipped.

## Verification

- `tests/integration/test_niche_canonicalization.py` (10, real Postgres): all
  deduplication paths, alias handling, idempotency, edge cases.
- Non-DB suite: 304 passed. DB suite: 119 passed, 1 skipped (2 pre-existing
  migration failures — Alembic env.py points to localhost; 1 transient setup
  error passed on rerun). ruff: clean.
- **Live** (dev DB, campaign "Slice 7 live demo"):
  - `canonicalize` → 3 candidates → 3 promoted (all unique), 0 merged,
    3 CampaignNiche rows created. Three canonical niches now exist:
    **Home Espresso Machine Repair**, **Reef Aquarium Nitrates**,
    **Sim Racing Hardware Setup** — all at `lifecycle_status=CANDIDATE`.
  - Rerun would produce 0 candidates (all already PROMOTED), 0 changes.

## Assumptions and open items

- The 0.82 cosine similarity threshold was chosen conservatively. With
  all-MiniLM-L6-v2 embeddings on short niche labels, 0.82 catches obvious
  rewordings ("Home Espresso" / "Espresso Machine Repair") while keeping
  distinct niches apart. Tunable via CLI flag.
- `parent_domain` on Niche is left NULL for now. A future slice (qualification)
  may infer it from the candidate's `is_broad_domain` flag or LLM.
- Promoted niches start at `lifecycle_status=CANDIDATE`. Advancing to ACTIVE
  is Slice 10 (verification). Qualification scoring is Slice 12.
