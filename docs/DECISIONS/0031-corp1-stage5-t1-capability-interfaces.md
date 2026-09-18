# ADR-0031 — CORP1 Stage 5, T1: Capability-Provider Interfaces

**Status:** Accepted
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 4 ("Capability Interface
Architecture") and Stage 5, task T1

## Context

CORP1's evidence sources are organized by what they prove (problem,
trend, transaction, etc.) rather than by platform, so the recursive
niche-discovery engine (T3) can fan a query out across every evidence
angle without a platform-specific call site per adapter. Nothing in the
codebase expressed this yet — adapters only implement the
platform-organized `SourceAdapter` (`corp/workers/adapters/base.py`).

## Decision

### One base, eight named interfaces, no shared method name

`EvidenceProvider` (ABC, no abstract method of its own) is the common
marker every capability interface inherits, so `isinstance(adapter,
EvidenceProvider)` identifies any capability-implementing adapter
regardless of which one(s). Each of the eight interfaces
(`ProblemProvider`, `SearchIntentProvider`, `TrendProvider`,
`PlanningIntentProvider`, `TransactionProvider`, `SolutionProvider`,
`MonetisationProvider`, `DissatisfactionProvider`) declares its own
uniquely named abstract method (`fetch_problems`, `fetch_trend`, etc.),
each returning `list[NormalizedContent]` — the schema adapters already
emit — and carries its own `evidence_type: ClassVar[EvidenceType]`
(T0's enum).

**Why not one shared method name** (e.g. a single `fetch_evidence()` on
the base, overridden per interface): the CORP1 spec's own adapter-to-
capability table has entries implementing two interfaces at once (Reddit
→ ProblemProvider, DissatisfactionProvider). A `ClassVar` named
`evidence_type` set differently by two parent interfaces collides under
Python's MRO the moment a class inherits both — `instance.evidence_type`
resolves to whichever base is listed first, silently discarding the
other. Distinct method names sidestep this entirely: T3 already knows
which `EvidenceType` applies from which method it called, and every
`evidence_type` reference in this codebase must be read off the
**interface class** (`ProblemProvider.evidence_type`), never off a
polymorphic instance — enforced by convention and documented directly in
the module docstring, and exercised by
`test_multi_capability_adapter_both_methods_work_independently`.

### EvidenceProvider declares `evidence_type` as an unset ClassVar

For static typing only — `CAPABILITY_INTERFACES` is typed
`tuple[type[EvidenceProvider], ...]`, so code iterating it (T3, tests)
needs `cls.evidence_type` to type-check on the base type. The annotation
carries no value on `EvidenceProvider` itself and must never be read
there; every concrete interface assigns its own.

### `CAPABILITY_INTERFACES` convenience tuple

All eight, in the CORP1 spec's Evidence Sources order — for T3's fan-out
loop and for T2's adapter-conformance tests, so neither has to hand-list
the eight names again.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/providers/capabilities.py` | New — `EvidenceProvider` + eight capability interfaces + `CAPABILITY_INTERFACES`. |
| `tests/workers/test_capabilities.py` | New — 32 tests: abstractness, evidence_type completeness (one-to-one against T0's `EvidenceType`), single- and multi-capability adapter conformance, the MRO collision demonstrated directly (both the trap and the fix). |

No existing adapter file was touched — per T1's frozen boundary, wiring
real adapters to these interfaces is T2's job.

## Verification

- `mypy --strict` clean on `capabilities.py`.
- 32 new tests pass (including a test that proves the MRO collision
  directly, added after Stage 8 review found the original multi-capability
  test only demonstrated correct usage, never the failure mode it claimed
  to guard against).
- Full `tests/workers/` suite (542 tests) still passes — zero regressions.

## Known risk for T2/T3 (flagged by Stage 8 review, not resolved here)

The "read `evidence_type` off the interface class, never the instance"
rule is enforced by **convention only** — nothing in the type system or at
runtime stops a future call site from writing `adapter.evidence_type` and
getting a silently wrong answer whenever `adapter` implements more than one
capability. `test_reading_evidence_type_off_the_instance_is_the_trap_not_the_fix`
proves the collision exists but cannot prevent someone from hitting it
elsewhere in the codebase later.

A structurally safer alternative exists and was deliberately not chosen in
T1: give `NormalizedContent` its own `evidence_type` field, set explicitly
by each `fetch_*` method's return value, so the type stays attached to the
data instead of depending on which method a caller remembers they called.
T1 kept `NormalizedContent` unchanged (it is `SourceAdapter`'s existing,
shared schema — widening it is a bigger, cross-cutting change than this
task's frozen scope). **T3, which is where `evidence_type` actually gets
stamped onto persisted `Evidence` rows, must stamp from the interface class
it queried through, not from the adapter instance** — this is the single
most important thing for T3 to get right from this task, and is worth a
second look at build time, not just at this review.

## Consequences

- T2 (wrap existing adapters) has a concrete interface to implement
  against, with worked examples in the test file for both single- and
  multi-capability adapters.
- T3 (recursive niche discovery) can iterate `CAPABILITY_INTERFACES`,
  look up which adapters implement each via `isinstance`, call the
  interface's named method, and tag results with that interface class's
  `evidence_type` — never the adapter instance's. See "Known risk" above:
  this is unenforced by the type system and needs deliberate care in T3.
