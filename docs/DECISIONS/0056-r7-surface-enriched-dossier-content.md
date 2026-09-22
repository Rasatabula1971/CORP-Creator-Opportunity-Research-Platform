# ADR-0056 — R7: Surface the enriched dossier content in the UI and the HTML dossier

**Status:** Accepted (Stage 8: ACCEPT, non-blocking, two applied — comparable products hoisted into a shared `_comparable_products` helper and rendered in the HTML too; collision-safe React key; Stage 9: accepted by user 2026-09-21, who moved the per-niche printable dossier into R10)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R7; audit finding #12; spec
dossier layout (pp. 30–31: Audience Analysis, Demand Validation, sample
evidence per cluster, comparable products)

## Context

Commit 71a862b added `audience_analysis`, `demand_validation`,
`opportunities[].sample_evidence`, `product_ideas[].comparable_products` and
`creator_score.component_scores` to the persisted dossier's `content`, and
R6 made those sections truthful. Nothing displayed them: the frontend
`PersistedDossier` type and `PersistedDossierPanel` knew only `niche_path`,
`recommendation` and a subset of `product_ideas`, and the live HTML dossier
(`GET /creators/{id}/dossier`) still rendered "generated with the persisted
dossier" stubs for Product Concepts and Recommendation with no Audience
Analysis at all. The human at the decision gate was deciding without the
spec's two evidence sections in front of them, and the two views of "the
dossier" had diverged.

## Decision

- **Backend (`generator.py`).** `generate()` (live HTML) now builds the same
  enriched sections as `generate_and_persist`: `audience_analysis`,
  `demand_validation`, product ideas, and the deterministic recommendation
  for the global top opportunity. Demand validation has no single niche in
  this view, so `_build_demand_validation` / `_niche_evidence_clause` now
  take a list of niche ids; the HTML path passes every niche the creator is
  linked to via `CreatorNiche`, the persisted path passes `[niche_id]`. An
  empty list yields `false()` (creator runs only). `_render` takes the
  extras as keyword arguments so existing callers/tests are unaffected.
  Comparable products come from one helper (`_comparable_products`) used by
  both paths. Residual, documented divergence: the persisted recommendation
  uses the niche-filtered top opportunity, the HTML view the global top (it
  has no niche), and HTML demand counts union every linked niche — read
  them as "all evidence touching this creator", not per-niche. At the
  Stage 9 gate the user chose to close this gap in R10: the printable
  dossier becomes per-niche (`?niche_id=`, defaulting to the creator's
  only niche, with per-niche links when there are several).
- **Template (`dossier.html.j2`).** New Audience Analysis section (counts,
  sentiment/urgency, language patterns, top questions per cluster); Demand
  Validation gains "External Evidence by Type" and "Source Highlights"
  tables ahead of the pre-existing diagnostics table; the Product Concepts
  and Recommendation stubs are replaced by real renders with honest empty
  states. The recommendation footer restates that the human gate decides.
- **Frontend.** `PersistedDossier.content` typed for the new keys
  (optional, so older persisted rows still type-check). `PersistedDossierPanel`
  renders Audience Analysis, Demand Validation (type counts + source
  highlights, zeros de-emphasised, honest empty state), Sample Evidence per
  opportunity, and Comparable products under each idea (http(s) URLs only
  become links, matching the template's rule).

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/dossier/generator.py` | `generate()` enriched; `_render` keyword extras; niche-id list scoping; `CreatorNiche`/`false` imports |
| `corp/workers/dossier/templates/dossier.html.j2` | Audience Analysis section; demand tables; real Product Concepts / Recommendation |
| `web/src/api/types.ts` | `PersistedDossier.content` new optional keys |
| `web/src/pages/CreatorDetailPage.tsx` | `AudienceAnalysisSection`, `DemandValidationSection`, sample evidence, comparable products; type import |
| `tests/workers/test_dossier_generator.py` | `test_stubs_present` updated (stubs gone, empty states asserted); new `test_enriched_sections_render_with_data` |
| `tests/api/test_endpoints.py` | New `test_dossier_html_renders_enriched_sections` (real route, seeded score) |

No migration. No model or schema changes (`PersistedDossierResponse.content`
is already `dict[str, Any]`).

## Verification

- `ruff check` (E,F,I,N,W) clean on `generator.py` and the template test;
  `tests/api/test_endpoints.py` still carries its two pre-existing F841 hits
  (R11). `mypy --strict` clean on `generator.py`.
- Frontend: `npx tsc --noEmit -p .` clean; `npx oxlint src` clean.
- `tests/workers/test_dossier_generator.py` + `tests/integration/test_dossier_persistence.py`
  + `tests/integration/test_registry_rescan.py` + `tests/api/test_handoff_endpoint.py`:
  47 passed; `tests/api/test_endpoints.py`: 21 passed (1 new).
- **Browser-verified** against the real servers (`.claude/launch.json`
  `corp-backend` + `corp-frontend`, dev DB seeded with one realistic
  creator via a scratch script — creator, audience observations with
  sentiment/urgency, cluster, scores, intent signal, competitors, product
  idea, a niche tree, a depth-0 drill run linked through a PROMOTED
  candidate, and a `research_more` run): `GET /creators/{id}/dossier`
  renders Audience Analysis (5 observations, 6 language patterns, top
  questions), Demand Validation (search intent 2, trend 1, transaction 3,
  monetisation 1, dissatisfaction 1; crowdfunding 1, Patreon/Substack 1,
  marketplace 2), Product Concepts and an APPROVE recommendation; after
  `POST …/dossier/generate` the creator page's Persisted Dossier panel
  shows the same figures plus sample evidence and comparable products. The
  only console errors were two 404s from `GET …/dossier/persisted` issued
  *before* generation — the panel's designed "no dossier yet" state — which
  return 200 afterwards.
- Full suite, `python -m pytest tests/ -q` with the 7 known pre-existing
  failures deselected, re-run after the Stage 8 tweaks: **1279 passed,
  1 skipped, 5 deselected** (0 failed; the pre-review run was identical).

## Consequences

- The human gate sees the spec's Audience Analysis and Demand Validation
  sections in both the dashboard panel and the printable HTML dossier, and
  the two views no longer diverge.
- The seeded demo creator remains in the dev DB (test data, per the user's
  decision on R3) and can be reused for later UI checks.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
`C:\Digital products\.claude\launch.json` (outside the repo) was created so
the desktop preview tool could start the two servers.
