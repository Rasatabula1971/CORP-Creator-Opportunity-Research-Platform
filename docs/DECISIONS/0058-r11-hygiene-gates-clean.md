# ADR-0058 — R11: Project-wide static gates clean, model/migration defaults aligned

**Status:** Accepted (Stage 8: ACCEPT, wording corrections applied; Stage 9: accepted by user 2026-09-22)
**Date:** 2026-09-22
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R11; audit findings #16, #20,
#22 and the static-gate survey (128 ruff hits, 13 mypy errors project-wide)

## Context

The repo's declared gates are `ruff check` and `mypy --strict`, but only
changed files had been held to them: a project-wide run reported 128 ruff
findings and 13 mypy errors, none of them behavioural. Separately, 19
columns carried a `server_default` in their migrations but not on the
model (autogenerate would propose spurious `DROP DEFAULT`s, and the models
misdocumented what a raw insert gets), `Dossier.niche_path` was typed
`dict` but stores a list, and two `tests/api` tests still asserted the
exception *message* after commit 5d239e2 deliberately reduced stored/
returned errors to the exception type name.

## Decision

- **Ruff.** Auto-fixed the safe rules (import order, `X | Y`, `datetime.UTC`,
  `collections.abc`, unused imports, default type args — 39 fixes); removed
  four unused test variables; wrapped 19 over-long lines (5 in adapters,
  14 in tests) by hand. Config: `UP042` (`str, Enum` → `StrEnum`, 27 hits)
  is **ignored, deliberately** — `StrEnum` changes `str(member)` from
  `Cls.NAME` to the value. Stage 8 found no current site that stringifies
  a member without `.value`/`.name`, so the rewrite would be safe today;
  the ignore is conservative (it stops a future `--fix` from taking that
  behavioural diff silently), not a correctness necessity. Per-file:
  Alembic-generated `migrations/versions/*`
  exempt from E501; `migrations/env.py` exempt from E402 (it must set the
  URL before importing the models). Result: `ruff check` clean.
- **mypy.** Four bare `dict` annotations in `ecosystem_estimator.py` →
  `dict[str, Any]`; `[[tool.mypy.overrides]]` with `ignore_missing_imports`
  for six third-party packages (umap, hdbscan, fair, googleapiclient,
  pytrends, yt_dlp). Precisely: none ships `py.typed`; `pytrends` is not
  installed at all (its imports are guarded, error was `import-not-found`);
  `yt_dlp` has typeshed stubs (`types-yt-dlp`) — installing those would be
  the stricter fix and is left as a follow-up. `fair` is imported only at
  `providers/fair.py:135`, so no typed code is silenced. Result:
  `mypy corp --strict` clean on 138 files.
- **Defaults.** `server_default` added to the 19 columns to match their
  migrations (enum names via `.name`, ints as strings, booleans via
  `sa.false()`); `migrations/env.py` now configures
  `compare_server_default=True` so `alembic check` sees this class of drift.
  `alembic check` → "No new upgrade operations detected" on `corp` and
  `corp_test`. `Dossier.niche_path` typed `list[dict[str, Any]] | None`.
- **Tests.** `test_registry_records_failure_without_raising` asserts
  `job.error == "RuntimeError"`; `test_unexpected_construction_error_…`
  asserts `detail == "TypeError"` — the hardened behaviour is the intended
  one (messages stay in the server log). These two leave the
  "known pre-existing failures" deselect list.

Not done: the five remaining pre-existing failures
(`test_intelligence_worker` ×2, `test_collector`, `test_dossier_pipeline`,
`test_campaign_pipeline_e2e`) predate this plan and are outside R11's
scope; they stay deselected and are listed as a follow-up.

## Files changed

35 files; grouped:

| Group | Files |
| --- | --- |
| Config | `pyproject.toml` (ruff ignore/per-file-ignores, mypy overrides) |
| Models: `server_default` | `corp/core/models/{campaign,campaign_niche,dossier,niche,niche_candidate,product_idea,research_query}.py` |
| Model types | `corp/core/models/dossier.py` (`niche_path`) |
| Alembic | `migrations/env.py` (`compare_server_default`, import order); `migrations/versions/{5c4a27a2ac92,6c88964d1240,a3b1c9d8e7f6,b4e7f2a1c3d5,d8a2e4f6b9c3}_*.py` (auto-fixed imports/annotations/whitespace only) |
| Lint auto-fix | `corp/core/models/{content,workflow}.py`, `corp/database.py`, `corp/workers/intelligence/{competitive_pipeline,niche_qualification}.py`, `tests/conftest.py`, `tests/warmstore/test_store_path.py` |
| Type args | `corp/workers/intelligence/ecosystem_estimator.py` |
| Line wraps | `corp/workers/adapters/{appstore,googletrends,marketplace}.py`; `tests/core/test_scoring_v2.py`, `tests/integration/test_stage4_models.py`, `tests/workers/{test_captions,test_extraction,test_multi_discovery}.py` |
| Unused vars | `tests/api/test_endpoints.py`, `tests/integration/test_ecosystem_estimator.py`, `tests/workers/test_multi_discovery.py` |
| Stale assertions | `tests/api/test_ops_no_db.py`, `tests/api/test_provider_health.py` |

No migration. No behaviour change intended anywhere.

## Verification

- `python -m ruff check` (project-wide, project config): clean.
- `python -m mypy corp --strict`: "no issues found in 138 source files".
- `python -m alembic check` on `corp` and on `corp_test`: no operations.
- Targeted: the touched test files + adapter tests: 131 passed; the two
  formerly failing tests + endpoints + multi-discovery + ecosystem: 69 passed.
- Full suite, now deselecting only the five unrelated pre-existing
  failures: **1283 passed, 1 skipped, 3 deselected** (0 failed — the two
  re-enabled tests pass; three of the five deselect ids are not collected
  in this run, hence 3).

## Consequences

- The declared gates are true again for the whole repo, not only for
  files touched in a given task; future ADRs can claim "clean" without the
  "(pre-existing repo-wide gap)" caveat.
- Autogenerate will no longer propose default drops; `alembic check` is
  meaningful for defaults.
- `UP042` stays a conscious exception, documented in `pyproject.toml`.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
