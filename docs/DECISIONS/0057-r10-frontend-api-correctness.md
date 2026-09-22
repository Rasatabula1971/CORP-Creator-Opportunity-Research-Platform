# ADR-0057 — R10: Frontend/API correctness batch

**Status:** Accepted (Stage 8: ACCEPT, non-blocking, two applied — `ge=1` on `/creators/{id}/decisions`; unlinked `niche_id` → 422; Stage 9: accepted by user 2026-09-22)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R10; audit findings #13,
#14, #15, #17, #18, #19, #21; follow-ups from R9 (Gate A schema) and R7
(per-niche printable dossier, user decision at the R7 gate)

## Context

Ten small, independent correctness gaps in the API surface and the React
dashboard, none of which changes pipeline behaviour:

- `/campaigns/{id}/niches` and `/campaigns/{id}/creators` were fetched with
  the server default of 50 and no total, so a recursive discovery run with
  hundreds of niches showed "(50)" with no hint of truncation; the niches
  route never set `X-Total-Count` (the creators route did).
- `ResearchRun.started_at` was typed non-null in TS while the schema is
  optional → "Invalid Date" for pending runs.
- `CreatorDetailPage` and `CampaignDetailPage` discarded the `error` of
  several hooks, so a failing sub-request rendered as "no data yet".
- The Gate A panel was offered for any creator not approved/rejected, but
  the server only accepts a Gate A decision from `human_review` (409).
- `Decision` in TS used `opportunity_id` and lacked `decided_by`.
- Approve had no visible handoff: `GET /dossiers/{id}/handoff` existed but
  nothing linked to it.
- Settings placeholder said port 8000; the client defaults to 8010.
- Two list routes allowed `limit=0`.
- (R9 follow-up) `DecisionCreate` still admitted `research_more`.
- (R7 follow-up) The printable HTML dossier had no niche scope.

## Decision

**Backend**
- `GET /creators/{id}/dossier?niche_id=`: `DossierGenerator.generate`
  takes an optional `niche_id`; with one — or when the creator is linked
  to exactly one niche — evidence scope and the recommendation's top
  opportunity are niche-filtered exactly as in `generate_and_persist`
  (reusing `_filter_niche_opportunities`). Only a multi-niche creator
  viewed without `niche_id` keeps the union/global-top fallback. An
  unknown `niche_id` is a 404; a niche not linked to the creator is a 422
  (Stage 8 finding). The page header shows "Dossier scope: <niche>
  (depth n)".
- `/campaigns/{id}/niches` sets `X-Total-Count`; that route,
  `/creators/{id}/competitors` and `/creators/{id}/decisions` gain `ge=1`
  on `limit`.
- `DecisionCreate.decision` is `Literal[APPROVE, REJECT, WATCH]`, so
  `research_more` at Gate A is a schema 422 (R9's route-level catch stays
  as defence in depth for the foreign-score case). The R9 test now asserts
  the validation body rather than the gate's message.

**Frontend**
- `useCampaignNiches` / `useCampaignCreators` use `getWithCount` at
  `LIST_LIMIT` (200); the campaign page shows the true total and "Showing
  the first N of M" when truncated, and surfaces both hooks' errors.
- `CreatorDetailPage` surfaces `useDossier` / `useClusters` /
  `useDecisions` errors as banners; the Gate A panel renders only when
  `creator.status === "human_review"`; the persisted-dossier header gains a
  "Printable dossier" link (`…/dossier?niche_id=<dossier niche>`) and, when
  approved, a "CORP2 handoff package" link to `/dossiers/{id}/handoff`.
- `ResearchRun.started_at: string | null` with "not started" in `RunsPage`;
  `Decision` fixed to `opportunity_score_id` + `decided_by`; settings
  placeholder → 8010.

## Files changed

| File | Change |
| --- | --- |
| `corp/api/routes.py` | `?niche_id=` on the HTML dossier (404 unknown, 422 unlinked); `X-Total-Count` + `ge=1` on campaign niches; `ge=1` on competitors |
| `corp/api/routes_ops.py` | `ge=1` on `/creators/{id}/decisions` |
| `corp/workers/dossier/generator.py` | `generate(creator_id, niche_id=None)` with niche scoping; `dossier_niche` passed to the template |
| `corp/workers/dossier/templates/dossier.html.j2` | "Dossier scope" header item |
| `corp/core/schemas/workflow.py` | `DecisionCreate.decision` restricted to approve/reject/watch |
| `web/src/api/hooks.ts` | Campaign list hooks paged with totals |
| `web/src/api/types.ts` | `Decision`, `ResearchRun.started_at` |
| `web/src/pages/CampaignDetailPage.tsx` | Totals, truncation note, hook errors |
| `web/src/pages/CreatorDetailPage.tsx` | Hook errors; Gate A gating; printable + handoff links; `getApiBase` import |
| `web/src/pages/RunsPage.tsx` | Null-safe start time |
| `web/src/components/SettingsPanel.tsx` | Placeholder port |
| `tests/api/test_endpoints.py` | R9 test adjusted to the schema 422; two new tests: per-niche HTML dossier (explicit niche 200 with scope header; single linked niche auto-scopes without the parameter; unlinked niche 422; unknown niche 404); campaign niches total header and `limit=0` → 422 |

No migration. No model changes.

## Verification

- `ruff check` (E,F,I,N,W) clean on the three changed backend source
  files; `mypy --strict` clean on them.
- `npx tsc --noEmit -p .` and `npx oxlint src` clean.
- `tests/api/test_endpoints.py` + `tests/workers/test_dossier_generator.py`
  + `tests/integration/test_dossier_persistence.py` +
  `tests/api/test_handoff_endpoint.py`: 59 passed (2 new).
- Browser (real servers, seeded creator/campaign from R7): the creator
  page shows the Gate A panel (status `human_review`) and a "Printable
  dossier" link carrying the persisted dossier's `niche_id`; the handoff
  link is correctly absent while the dossier is `pending_review`;
  `GET …/dossier` with no parameter on this single-niche creator renders
  "Dossier scope: Home Espresso (depth 1)"; an unknown `niche_id` returns
  404 "Niche not found"; `/campaigns/{id}/niches` returns
  `X-Total-Count`; the campaign page headings read "Niches (1)" /
  "Onboarded Creators (1)" from the totals. One console ReferenceError
  (`getApiBase is not defined`) was observed during the session; it came
  from Vite's hot-reload snapshot taken between the panel edit and the
  import edit — the module Vite serves after the final edit imports
  `getApiBase`, the page renders without the error boundary, and `tsc` is
  clean.
- Full suite, `python -m pytest tests/ -q` with the 7 known pre-existing
  failures deselected, re-run after the Stage 8 tweaks: **1281 passed,
  1 skipped, 5 deselected** (0 failed; identical to the pre-review run).

## Consequences

- Both dossier views now share the same per-niche evidence scope and
  recommendation for the normal single-niche case; the printable page is
  reachable from the dashboard, as is the CORP2 handoff after Approve.
- Failures in sub-requests are visible rather than disguised as empty
  states; list pages tell the truth about truncation.
- Gate A can no longer be offered when the server would refuse it.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
