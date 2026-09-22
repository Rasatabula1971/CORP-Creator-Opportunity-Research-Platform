# CORP1 Remediation Plan — Spec Alignment (September 2026)

**Status:** COMPLETE 2026-09-22 — all eleven R-tasks accepted and committed (ADR-0048 … ADR-0058). Follow-ups: R12 and the items under "Deliberately out of scope".
**Source:** Whole-app audit against `CORP1_Product_Spec_Build_Plan.pdf` (three
independent review passes: backend pipeline, API/frontend, schema) plus a
project-wide static-gate run. Full findings list is in the session that
produced this document; the numbered audit items are cited below as `#n`.
**Decisions taken at acceptance:**
- R3 backfills existing rows and tightens `evidence.evidence_type` /
  `evidence.origin` to `NOT NULL` (database holds only test data).
- This plan lives in the repo alongside the ADRs; each R-task's ADR cites it.

Ordering: R1 → R2 → R3 → R6 → R4 → R5 → R8 → R9 → R7 → R10 → R11.
R6 runs ahead of Phase B because it is a regression from the same session as
R1 and is isolated to one file.

## Phase A — Restore the Provenance Invariant

| Task | Audit | Files | Acceptance | Status |
| --- | --- | --- | --- | --- |
| **R1** Platform→type mapping uses the exact `source_platform` strings adapters emit | #1 | `corp/core/models/evidence.py`, `tests/core/test_evidence_type_mapping.py` | Every `KNOWN_PLATFORMS` entry maps; mapped type ∈ the adapter's declared capability interfaces | Done — ADR-0048, commit 785a627 |
| **R2** LLM-derived Evidence rows set `origin = INFERENCE` | #4 | `competitive_pipeline.py`, `intent_pipeline.py`, `product_idea.py` docstring | Every `Evidence(` constructor in `corp/` sets both fields; `EvidenceOrigin.INFERENCE` used in real code | Done — ADR-0049, commit 07ae862 |
| **R3** Backfill + `NOT NULL` | new | one Alembic migration | Backfill via corrected mapping; inference `source_type`s → `INFERENCE`; both columns `NOT NULL`; DB-level test on `corp_test` | Done — ADR-0050 |

## Phase B — Make the niche tree real

| Task | Audit | Files | Acceptance | Status |
| --- | --- | --- | --- | --- |
| **R4** Populate `Niche.parent_niche_id` / `depth` on promotion | #3 | `niche_canonicalization.py` | After a depth-3 drill, `_niche_path()` returns ≥3 nodes; handoff package shows full path; parent resolves via the parent candidate's `niche_id` (PROMOTED or MERGED); depth derived from the parent niche; no cycles | Done — ADR-0052 |
| **R5** Depth cap on `research_more`; fan-out includes `crowdfunding` + `patreon_substack`; recheck clock set at promotion; `NicheLifecycleStatus.EXCLUDED` set on exclusion | #6 #9 #11 #10 | `niche_discovery.py`, `niche_canonicalization.py` | No candidate persisted above `max_depth`; TRANSACTION/MONETISATION evidence collected in drill; no promoted niche with NULL `next_recheck_at` | Done — ADR-0053 |

## Phase C — Make the dossier truthful

| Task | Audit | Files | Acceptance | Status |
| --- | --- | --- | --- | --- |
| **R6** Scope dossier evidence via `CreatorNiche → ResearchRun.niche_id` ∪ creator runs | #2 | `dossier/generator.py` | Integration test: niche-discovery evidence → non-zero `demand_validation.signals`; "using global top" warning no longer fires for candidate-linked evidence | Done — ADR-0051 |
| **R7** Surface persisted dossier content end-to-end | #12 | `web/src/api/types.ts`, `CreatorDetailPage.tsx`, `dossier.html.j2` | `audience_analysis`, `demand_validation`, `sample_evidence`, `comparable_products`, `component_scores` typed and rendered; template stubs retired; browser-verified | Done — ADR-0056 |
| **R8** Re-scan scheduler robustness | #7 #8 | `scheduler/registry_rescan.py` | `next_recheck_at` advanced only on success; per-dossier savepoint; resurface to `PENDING_REVIEW` only when content hash changes | Done — ADR-0054 |

## Phase D — API/UI correctness and hygiene

| Task | Audit | Files | Acceptance | Status |
| --- | --- | --- | --- | --- |
| **R9** Gate A returns 422 on invalid decision / foreign score id | #5 | `corp/api/routes.py`, test | Route-level `ValueError` → 422 (same pattern the persisted-dossier and handoff routes already use); no 500 path | Done — ADR-0055 |
| **R10** Frontend fixes | #13 #14 #15 #17 #18 #19 #21 | `hooks.ts`, `types.ts`, `CreatorDetailPage.tsx`, `CampaignDetailPage.tsx`, `RunsPage.tsx`, `SettingsPanel.tsx`, `routes.py` | Pagination + `X-Total-Count`; nullable `started_at`; hook errors surfaced; handoff link on Approve; Gate A panel only in `human_review`; `Decision` type fixed; `limit ge=1`; Gate A request schema restricted to approve/reject/watch (R9 follow-up); printable dossier per niche — `GET /creators/{id}/dossier?niche_id=` defaulting to the creator's only niche, with a per-niche link in the UI when there are several (R7 follow-up, user decision 2026-09-21) | Done — ADR-0057 |
| **R11** Hygiene | #16 #20 static gates | models (`server_default`), `dossier.py` type, `pyproject.toml` mypy overrides, two stale test assertions | `ruff check` and `mypy --strict` clean project-wide; no behaviour change | Done — ADR-0058 |

## Planned after this run (needs its own Stage 3/4 pass first)

| Task | Why | Design questions |
| --- | --- | --- |
| **R12** Watch re-scan re-collects evidence | Decided at R8's gate (2026-09-21). Today the re-scan only re-renders from the current `OpportunityScore`; nothing re-runs research for a watched creator, so "resurface if the evidence strengthens" cannot trigger on its own. R8's savepoint + fingerprint are the foundation. | Chain `research_more` (niche) + creator research pipeline (collect → extract → cluster → intent → score) before regeneration; per-tick cost/LLM budget and max dossiers per tick; numeric definition of "strengthened" (score delta vs. new-evidence count); interaction with the weak-niche revisit state below. |

## Deliberately out of scope

- **Weak-niche "revisit later" state** (3–6 month window OR renewed trend
  signal) — undesigned; needs Stage 3/4 first. Likely designed together
  with R12.
- **T11 Pinterest / T12 Brave Search** — parked pending API access.
- **`str, Enum` → `StrEnum` (27 UP042 hits)** — R11 chose to ignore the
  rule in config rather than rewrite: `StrEnum` changes `str(member)`
  output, which reaches logs/f-strings; stored labels would be unchanged.
- **Five pre-existing test failures** — triaged in R11b (ADR-0059): two ids
  were stale (file gone), one was an event-loop/pool ordering defect in the
  test harness (fixed in conftest), one was a renamed-method test, one was a
  real collector bug (parented question/review never became an
  interaction). Suite now runs with no deselects. `types-yt-dlp` stubs
  adopted in the same task.
