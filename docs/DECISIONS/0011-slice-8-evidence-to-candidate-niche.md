# Slice 8 — Evidence → Candidate Niche

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, Slice 8 / §15 Stage A / §16 / §18 / ADR-007

## What shipped

Stored discovery evidence for a campaign can be grouped into evidence-backed,
staged niche candidates.

- `corp/core/models/niche_candidate.py` — `NicheCandidate` (staged niche: label,
  description, how it was named, evidence-diversity numbers, provenance, status,
  `superseded_at`, optional `niche_id` for Slice 9) and `NicheCandidateEvidence`
  (one row per member evidence, with similarity to the cluster centroid).
  `CHECK (evidence_count >= 1)` — a candidate row without evidence is rejected by
  the database, not just by convention. Migration `f6a7b8c9d0e1`.
- `corp/workers/intelligence/niche_candidates.py` — `NicheCandidateGenerator`:
  loads every evidence row collected by the campaign's `NICHE_DISCOVERY` runs,
  embeds with the same local sentence-transformer problem clustering uses, runs the
  same UMAP + HDBSCAN path, and writes one candidate + member rows per cluster under
  a `NICHE_DISCOVERY` run (`pipeline=niche_candidates`, `campaign_id` set). Noise
  points produce nothing. A rerun supersedes the campaign's still-staged candidates
  (latest wins, nothing deleted — the convention clusters and scores already use).
- `corp/workers/intelligence/niche_naming.py` — the LLM's only role: name a cluster
  from its member texts (§16). It must cite `evidence_terms`; the answer is used
  only when every cited term occurs verbatim (case/space-insensitive) in those
  texts. Otherwise — or if the call fails — the deterministic keyword label from
  the clusterer stands, and the rejected name and its ungrounded terms are kept in
  `extra` for audit. `is_broad_domain` (ADR-007) is recorded either way; acting on
  it is qualification (Slice 12). Strict-mode schema, `NAMING_PROMPT_VERSION`.
- CLI: `candidates <campaign_id> [--min-cluster-size N] [--no-llm]`.
- `clustering.py` — one shared fix: UMAP is skipped when the input has no more
  points than `n_components + 1` (its spectral init fails there); HDBSCAN runs on
  the raw embeddings. Found by the 4-item test sets; would also have hit any small
  creator's problem clustering.

Reuse, not rebuild: `Evidence`, `ResearchRun` (Slice 5 kwargs), `start_run` /
`finish_run` / `supersede`, `embed_texts`, `cluster_observations`, the FAIR/pool
provider with `schema=`.

## Acceptance criteria → how each is met

- **Candidate cannot exist without supporting evidence.** The only code path that
  creates candidates iterates clusters, and a cluster is a set of evidence rows;
  member rows are flushed in the same unit of work; `CHECK (evidence_count >= 1)`
  rejects a direct insert (`test_candidate_without_evidence_is_impossible`).
- **Candidate naming is traceable to cluster/evidence.** `naming_method` is `llm`
  or `keywords`; `naming_terms` holds the cited terms, each verified against the
  member texts; `naming_prompt_version` / `naming_model_version` /
  `embedding_model` / `research_run_id` complete the chain.
- **Generic unsupported LLM niche creation is impossible through this path.** The
  LLM cannot add a candidate, cannot add evidence, and cannot name one with terms
  the evidence does not contain. An ungrounded name is discarded, not "trusted with
  low confidence".

## Verification

- `tests/workers/test_niche_naming.py` (10): grounding rules, schema passed,
  prompt shows 12 of N, broad flag, clamping, non-dict answer, provider failure.
- `tests/integration/test_niche_candidates.py` (9, real Postgres): clusters →
  candidates + member links + diversity numbers, LLM name accepted vs rejected
  (ungrounded), rerun supersedes, empty campaign, naming failure keeps the
  keyword candidate, no provider, other campaigns' evidence excluded, noise
  produces nothing, DB rejects an evidence-less candidate, unknown campaign.
- `tests/workers/test_clustering.py` +1 (tiny input clusters without UMAP).
- Non-DB suite: 304 passed. DB suite: 110 passed, 1 skipped, 0 failures. ruff/mypy: no new findings
  on changed lines (clustering.py's stub/typing findings predate this slice);
  import-linter 2 kept. Migration up on `corp_test` and dev.
- **Live** (dev DB, campaign "Slice 7 live demo"):
  - 4 yt-dlp discovery queries → 38 new evidence (10+10+10+8), 0 duplicates.
  - `candidates` → 3 candidates from 40 evidence, 0 noise, 0 ungrounded names.
  - FAIR naming: all 3 via `gemini-3.5-flash-lite`, `STRUCTURE_VALIDATED`.
  - Candidates: **Home Espresso Machine Repair** (23 ev, 18 authors), **Reef
    Aquarium Nitrates** (10 ev, 6 authors), **Sim Racing Hardware Setup** (7 ev,
    7 authors). All grounded — every cited term appears in the member texts.

## Problems found and fixed during this slice

1. **UMAP cannot initialise on ≤ 6 points** (`scipy eigsh: k >= N`). Shared
   clusterer; fixed as above.
2. **HDBSCAN calls one undifferentiated group "noise".** Four near-identical
   items with `min_cluster_size=3` yielded zero clusters. Not a bug — one blob has
   no density contrast — but it means a campaign whose evidence is all one topic
   produces no candidate until a second topic exists. Noted for Stage A's query
   planning; tests use two groups.
3. **Noise assignment on tiny inputs is not deterministic through UMAP.** The
   noise-handling test stubs the clusterer rather than depend on it.

## Assumptions and open items

- Evidence text is `Evidence.raw_text` — for yt-dlp search results that is the
  video title (plus description when present). Titles cluster well enough to
  stage candidates; verification (Slice 10) is where deeper text arrives.
- Time diversity uses `collected_at` (collection time), because discovery evidence
  does not carry the source's publish time. Honest column names
  (`earliest/latest_collected_at`); a publish-time column on `Evidence` is a
  candidate change for Slice 10.
- `source_count` is distinct platforms; `author_count` distinct handles. With one
  adapter (YouTube) `source_count` is 1 for now.
- Candidates are staged only. Canonicalization / alias resolution / promotion to
  `Niche` is Slice 9; qualification is Slice 12.
