# ADR-0060 — R12b: Creator.status mirrors the dossier decision gate

**Status:** Accepted (Stage 8: ACCEPT, non-blocking, fixture tightened, mirror gap recorded in design §4.6; Stage 9: accepted by user 2026-09-22, who also accepted wiring product ideation into the normal Generate Dossier path as part of R12a)
**Date:** 2026-09-22
**Reference:** `docs/design/R12_watch_rescan_recollect.md` §4.2 Option A
(frozen 2026-09-22); R12 task table row R12b

## Context

The dossier decision gate (`POST /dossiers/{id}/decision`, T8) records an
append-only `HumanDecision` and sets `Dossier.status` — documented as "a
denormalized mirror of the latest HumanDecision". It never touched
`Creator.status`, so after every one of a creator's dossiers had been
watched, approved or rejected the creator still read `human_review`. Two
consequences: the dashboard shows a creator "in review" with nothing to
review, and — the reason this is R12's first task — `ResearchOrchestrator`
may only restart from `DISCOVERED` or `WATCHING`, so a watched creator could
not be re-researched at all. R12c (Watch re-collects evidence) needs the
creator to actually be `WATCHING`.

## Decision

- `corp/core/state/gates.py`: `creator_status_for_dossiers(statuses)` gives
  the status implied by a creator's **active** (non-superseded) dossiers,
  by precedence: any `APPROVED` → `APPROVED`; any `PENDING_REVIEW` /
  `RESEARCH_MORE_IN_PROGRESS` → `HUMAN_REVIEW`; any `WATCHING` →
  `WATCHING`; all `REJECTED` → `REJECTED`. `mirror_creator_status(session,
  creator_id)` applies it **only through a legal state-machine move**; an
  illegal move (a creator not at a gate-adjacent status) is logged and
  skipped so the human's decision is never rejected because of it.
- `routes_ops.record_dossier_decision` calls the mirror after setting the
  dossier status, before commit. Research More leaves the creator at
  `HUMAN_REVIEW` (the dossier is still awaiting a human); R12a decides how
  the creator moves during re-research.
- `corp/core/state/machine.py`: `WATCHING → APPROVED` and `WATCHING →
  REJECTED` become legal. The dossier gate already accepts decisions on a
  `WATCHING` dossier; without these the mirror could never follow them.
- Migration `f6a1e362c878`: backfill for creators at `HUMAN_REVIEW` that
  have active dossiers, using the same precedence in SQL. Downgrade
  restores `HUMAN_REVIEW` for creators whose gate history is dossier-only
  (no `GATE_A` decision). Applied to `corp` and `corp_test` (no rows
  affected in either — the seeded demo creator's dossier is
  `pending_review`).

Multi-niche rule (design §4.2): a creator is `WATCHING` only when no active
dossier still awaits a human — `test_pending_dossier_on_another_niche_keeps_creator_in_review`.

## Files changed

| File | Change |
| --- | --- |
| `corp/core/state/machine.py` | `WATCHING → APPROVED / REJECTED` |
| `corp/core/state/gates.py` | `creator_status_for_dossiers`, `mirror_creator_status` |
| `corp/api/routes_ops.py` | Mirror call in the dossier gate |
| `migrations/versions/f6a1e362c878_r12b_mirror_creator_status_from_dossiers.py` | Backfill |
| `web/src/api/hooks.ts` | Dossier-decision mutation also invalidates creator detail/list queries |
| `tests/core/test_state_machine.py` | New transitions |
| `tests/api/test_dossier_decision_endpoint.py` | Mirror per decision (parametrised); watch-then-approve; multi-niche precedence; non-gate creator leaves the decision intact with a warning |

No model changes (no new columns).

## Verification

- `python -m ruff check` (project-wide): clean. `mypy --strict` clean on
  the three source files and the migration.
- `alembic heads` → `f6a1e362c878`; both DBs upgraded.
- `tests/core/test_state_machine.py` + `test_gates.py` +
  `test_transitions.py` + `tests/api/test_dossier_decision_endpoint.py` +
  `test_endpoints.py` + `tests/integration/test_registry_rescan.py` +
  `test_migration.py`: 72 passed (6 new).
- Full suite, no deselects: **1294 passed, 1 skipped, 0 failed**.
- Frontend: `npx tsc --noEmit -p .` and `npx oxlint src` clean.

## Consequences

- The creator list and detail page now agree with the dossier gate; the
  Gate A panel (R10: shown only at `human_review`) disappears once a
  creator's dossiers are all decided.
- `ResearchOrchestrator` can restart for a watched creator — the
  precondition R12c relies on.
- Frontend: `useRecordDossierDecision` invalidated only the persisted
  dossier and jobs queries, so the creator's status badge and Gate A panel
  would have gone stale after a decision; it now also invalidates the
  creator detail and list queries (`web/src/api/hooks.ts`).

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
