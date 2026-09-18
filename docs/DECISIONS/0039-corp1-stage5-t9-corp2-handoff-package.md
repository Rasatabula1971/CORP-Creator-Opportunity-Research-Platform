# ADR-0039 — CORP1 Stage 5, T9: CORP2 Handoff Package

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, "CORP1 → CORP2 Handoff
Package (Frozen)" and Stage 5, task T9

## Context

T9's frozen scope is one new file: `corp/workers/handoff/corp2_export.py`.
Forbidden: no direct writes to any CORP2 (`Acq*`-prefixed) table — CORP1
never reaches across the boundary; it produces a package CORP2 pulls or
receives via API. No migration. Acceptance criteria: the package
contains the full dossier, the complete evidence trail, the full niche
drill-down path, and the reviewer's decision-gate notes, "matching the
Stage 3 Handoff Package definition exactly." The frozen Stage 3 section
itself reads: "On Approve, CORP1 produces a decision package containing:
the full dossier; the complete evidence trail — every evidence record
and source link the dossier was built from; the full niche drill-down
path ... showing how specific the opportunity is; your review notes
from the decision gate. This mirrors the Acquisition system's
dossier-snapshot pattern: CORP2 references this package rather than
querying the CORP1 research database directly." The Automation Matrix
lists "Handoff package creation" as "AUTO, triggered by Approve."

## Decisions

### A precise reading of the test requirement's wording

T9's frozen "Tests" bullet says the package must be "fully
reconstructable from `Dossier` + `dossier_evidence` + `Niche.
parent_niche_id` walk alone, with no other CORP1 table access
required." Taken with maximal literalness, this would exclude even a
`HumanDecision` lookup — but the acceptance criterion in the same task
card requires "the reviewer's decision-gate notes" in the package, and
`Dossier.content` (rendered by T6's `DossierGenerator` *before* any
human ever reviews it) cannot contain a note written after the fact.
There is no other place in the schema those notes could live — T8 wrote
them into `HumanDecision.rationale`, by design (an append-only ledger,
not a second copy on `Dossier`).

Read this way: the three named relations are the ones needed to avoid
re-deriving the dossier from the *heavier upstream pipeline* it was
originally rendered from (`ProblemCluster`, `OpportunityScore`,
`CreatorScore`, `NicheCandidate` — none of which this module imports or
queries, verified by a static AST-import test, not just a source-text
search that would trip over the module's own docstring). A single,
direct `HumanDecision` lookup by `dossier_id` is the one addition beyond
the three named relations, and it exists specifically to satisfy the
acceptance criterion's own fourth bullet. This is a documented, low-risk
reading of ambiguous wording, not a scope-widening decision — resolved
without escalating to the user, unlike T8's engine-capability gap, which
had no reading that avoided a real missing capability.

### `build_handoff_package(session, dossier_id) -> HandoffPackage`

Pure read, no writes anywhere — trivially satisfies "no direct writes to
any CORP2 table" since it writes to nothing at all. Queries, in order:

1. `Dossier` by id — 404-equivalent `ValueError` if missing.
2. Requires `Dossier.status == DossierStatus.APPROVED` — raises
   otherwise. Matches the Automation Matrix ("triggered by Approve");
   building a package for a non-approved dossier is a caller error worth
   catching early, the same pattern `DossierGenerator`/`RecursiveNiche
   Discovery` already use for their own precondition checks.
3. `Evidence` joined through `DossierEvidence` (T6's existing join
   table) — the complete evidence trail, every row T6 already linked
   when generating the dossier.
4. `Niche` walked via `parent_niche_id` from the dossier's niche back to
   its root, then reversed to root→leaf order (matching the spec's own
   example: Automotive → Track Builds → Suspension).
5. One `HumanDecision` row: `dossier_id` match, `decision == APPROVE`,
   latest by `decided_at` — the reviewer's rationale, who decided, and
   when. `None` for all three fields if none exists (robustness, not
   expected in normal operation since this only runs post-Approve).

Returns a frozen `HandoffPackage` dataclass (plus `NichePathEntry`/
`EvidenceTrailEntry`) with a `to_dict()` for JSON-safe serialization
(datetimes → ISO 8601 strings, recursively through the nested entries) —
matching "CORP2 pulls or receives via API" without this task adding an
actual endpoint (out of its frozen scope; a later task's job, same as
T7 left pipeline wiring to T21).

### Not wired to T8's Approve path yet

T8 already ships and is already committed; its Approve branch explicitly
defers calling into T9 ("`Dossier.status == APPROVED` is what T9's
export job will query for once it exists," ADR-0038). T9's own frozen
scope is one new file, not `corp/api/routes_ops.py` — wiring an actual
trigger (a background job, a webhook, whatever "AUTO, triggered by
Approve" ends up meaning operationally) is left to whichever later task
actually adds the CORP1→CORP2 transport, consistent with this task's
"produces a package CORP2 pulls **or receives via API**" phrasing
leaving the transport open. Building the package function itself,
callable directly and testable in isolation, is what this task's frozen
scope actually asks for.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/handoff/__init__.py` (new) | Empty, matches sibling worker packages' convention (e.g. `corp/workers/dossier/__init__.py`). |
| `corp/workers/handoff/corp2_export.py` (new) | `HandoffPackage`/`NichePathEntry`/`EvidenceTrailEntry` dataclasses, `build_handoff_package()`, `_walk_niche_path()`. |
| `tests/integration/test_corp2_export.py` (new) | 9 tests: happy path, zero-linked-evidence (added post-Stage-8-review), decision notes present/absent, niche-path root-to-leaf, dossier-not-found, dossier-not-approved, `to_dict()` JSON-round-trip, and a static AST-import check proving no upstream-pipeline table is imported (docstring updated post-review to disclose its own attribute-access/importlib blind spot). |

No changes to any model file, migration, or any CORP2/`Acq*`-prefixed
table (there are none to write to — the module contains no `session.
add`/`session.commit` at all).

## Verification

- `mypy --strict` clean on `corp/workers/handoff/corp2_export.py`.
- `ruff check` clean on the new module and the new test file.
- `tests/integration/test_corp2_export.py`: 9 passed (8 at Stage 7, +1
  post-Stage-8-review).
- Full `tests/integration/` + `tests/api/`: 337 passed (up from T8's 329,
  the 8 new tests at Stage 7), 1 pre-existing unrelated skip, zero
  regressions.
- Full `tests/workers/`: 575 passed, zero failures.

## Stage 8 review: ACCEPT, two non-blocking items applied

Independent review confirmed the HumanDecision-lookup interpretation
(item 1) as sound and correctly resolved without escalation — a genuine
internal contradiction between the frozen card's own Acceptance-criteria
and Tests bullets, contained entirely within T9's one allowed file,
unlike T8's actual cross-file capability gap. Also confirmed
`build_handoff_package`'s correctness, the `APPROVED`-only precondition,
test rigor, and the scope boundary (zero changes outside `corp/workers/
handoff/`). Two non-blocking suggestions applied before commit: a
docstring note disclosing the AST-import check's blind spot (attribute
access via an aliased module import, or `importlib.import_module`,
would not be caught), and a new test for a dossier with zero linked
evidence.

## Consequences

- The next task touching the CORP1→CORP2 boundary (transport/trigger
  wiring) can call `build_handoff_package(session, dossier_id)` directly
  — it's already fully tested and returns a JSON-safe snapshot via
  `to_dict()`.
- `HandoffPackage`'s shape (five top-level fields plus the three nested
  lists/records) is now the de facto contract CORP2 will consume;
  changing it later is a breaking change for whichever task wires the
  actual transport.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF, none of which T9 touched — the same pre-existing
dev-environment changes disclosed in every ADR since T4. Not staged as
part of this task's commit.
