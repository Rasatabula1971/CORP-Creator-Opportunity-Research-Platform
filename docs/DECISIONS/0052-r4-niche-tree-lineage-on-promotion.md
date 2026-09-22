# ADR-0052 — R4: Carry drill lineage onto Niche.parent_niche_id / depth

**Status:** Accepted (Stage 8: ACCEPT; findings 2, 3, 4, 5, 6, 7 applied before commit; Stage 9: accepted by user 2026-09-21)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R4; audit finding #3; spec
Stage 4 data model ("parent_niche_id is the source of truth for tree
structure") and the T9 handoff package's "niche drill-down path root-to-leaf"

## Context

T3's drill engine records `NicheCandidate.parent_candidate_id` and `depth`,
but `NicheCanonicalizer` created every `Niche` with the model defaults
(`parent_niche_id = NULL`, `depth = 0`), discarding the tree. Grep confirmed
`parent_niche_id` was never assigned anywhere in `corp/`. Consequences:
`DossierGenerator._niche_path()` and `corp2_export._walk_niche_path()`
always returned a single node, `research_more()` fell back to
`niche.depth + 1 = 1` for every niche, and the spec's tree was only
reconstructible from the candidate table.

## Decision

- `_staged_candidates` orders by `depth ASC, evidence_count DESC` (was
  `evidence_count DESC` only) so a parent's niche exists before its children
  resolve it.
- `_parent_niche(cand)`: the `Niche` the parent candidate resolved to —
  PROMOTED *or* MERGED, since lineage attaches to whichever niche the
  parent ended up in (Stage 8 finding 4; the plan row's "filters
  `status == PROMOTED`" wording was corrected to match). `None` for depth-0
  candidates or when the parent was rejected / not canonicalized — the
  candidate then becomes a root at depth 0.
- **Depth is derived, not copied**: `depth = parent_niche.depth + 1`, never
  `cand.depth` (Stage 8 finding 3: a parent that merged into a niche at
  another depth would otherwise leave the child inconsistent with the walk).
- **Promote**: new `Niche` gets `parent_niche_id` and the derived depth.
- **Merge**: if the existing niche has no lineage yet and this candidate
  resolves a parent, fill it in; never re-parent a niche that already has
  lineage; and never create a cycle — `_is_self_or_descendant` walks the
  prospective parent's ancestors and refuses if the niche itself appears
  (Stage 8 finding 2 showed a two-run inversion could otherwise produce
  NA → NB → NA; the dossier/handoff walkers have `seen` guards so it could
  not hang, but the path would be wrong).
- **Backfill migration `adc83dc5b00e`**: for each niche with no parent whose
  PROMOTED candidate has a parent candidate that resolved to a different
  niche, set `parent_niche_id = that niche` and `depth = its depth + 1`.
  Downgrade clears ALL lineage (including rows the canonicalizer writes
  after the upgrade) — acceptable only because pre-R4 every niche was
  provably a depth-0 root; stated in the file. Applied to `corp` (re-run
  after the depth correction) and `corp_test`.

Not done here: MERGED-based lineage for pre-existing niches in the
backfill (only PROMOTED is unambiguous); `NicheLifecycleStatus.EXCLUDED`
and the recheck clock at promotion (R5).

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/intelligence/niche_canonicalization.py` | Ordering; `_parent_niche_id`; lineage on promote/merge; module docstring |
| `migrations/versions/adc83dc5b00e_r4_backfill_niche_tree_lineage.py` | New backfill |
| `tests/integration/test_niche_canonicalization.py` | Five tests: promotion carries lineage (child has MORE evidence than parent, proving the ordering fix); merge fills missing lineage (depth derived) but never re-parents a niche that has lineage even when a parent resolves; child merging into its parent's niche is not self-parented; a two-run inverted tree cannot create a deeper cycle; a canonicalized three-level chain yields a three-node root-to-leaf path through `DossierGenerator._niche_path` (the R4 acceptance criterion, Stage 8 finding 7) |

No model changes.

## Verification

- `ruff check` (E,F,I,N,W) clean on all three files; `mypy --strict` clean
  on the source file and the migration.
- `alembic heads` → single head `adc83dc5b00e`; both DBs upgraded.
- `tests/integration/test_niche_canonicalization.py`: 15 passed (5 new).
- Full suite, `python -m pytest tests/ -q` with the 7 known pre-existing
  failures deselected, re-run after the Stage 8 fixes: **1264 passed,
  1 skipped, 5 deselected** (0 failed).

## Consequences

- New niches form a real tree; `niche_path` in persisted dossiers and the
  CORP2 handoff package now walk root-to-leaf; `research_more()` anchors
  at the correct depth.
- Existing niches in other environments get lineage where a PROMOTED
  candidate chain makes it recoverable; otherwise they stay roots.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
