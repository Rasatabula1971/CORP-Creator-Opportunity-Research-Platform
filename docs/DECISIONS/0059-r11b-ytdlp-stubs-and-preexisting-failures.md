# ADR-0059 — R11b: yt-dlp type stubs; triage of the five "pre-existing" test failures

**Status:** Accepted (Stage 8: REVISE on two ADR-text claims, corrected — code confirmed correct; no second round, disclosed at the gate; Stage 9: accepted by user 2026-09-22)
**Date:** 2026-09-22
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` follow-ups from R11 (ADR-0058):
"`types-yt-dlp` would tighten mypy" and "five pre-existing test failures need
their own triage". User asked for both on 2026-09-22.

## Context

R11 silenced `yt_dlp` with a mypy `ignore_missing_imports` override although
typeshed stubs exist. Separately, every full-suite run since this plan began
deselected five test ids as "known pre-existing failures" without anyone
having looked at why. (Stage 8 on this task corrected the first draft's
account of the collector failure — see the triage table.)

## Triage of the five

| Test id | Finding | Action |
| --- | --- | --- |
| `tests/workers/test_intelligence_worker.py::…by_parent_id` | File no longer exists — a stale id (that is why the suite reported "5 deselected" as 3 collected). | Dropped from the list. |
| `tests/workers/test_intelligence_worker.py::…orders_by_confidence` | Same stale file. | Dropped. |
| `tests/integration/test_campaign_pipeline_e2e.py::test_campaign_pipeline_discover_to_dossier` | Passes alone and after `tests/integration`/`tests/workers`/`tests/core`, but **fails after `tests/api`** with `RuntimeError: Event loop is closed`: `corp.database`'s pooled asyncpg engine binds its connections to the event loop that first used it (the app tests), and pytest-asyncio gives each test its own loop; this is the only test that goes through `corp.database` (`jobs.run_campaign_pipeline`) rather than the conftest engine. A test-harness defect, not an app bug — in production one loop owns the pool. | Autouse fixture in `tests/conftest.py` disposes the app engine before each test (pool rebuilds lazily on the current loop). Bisected by running each directory followed by the e2e test. |
| `tests/integration/test_dossier_pipeline.py::test_load_observations_orders_by_confidence` | Test called `DossierGenerator._load_observations`, renamed to the batched `_load_observations_batch` in an earlier refactor; the behaviour it checks (10-cap, confidence-desc) is unchanged. | Test updated to the batch API; also asserts the ordering explicitly. |
| `tests/integration/test_collector.py::test_collect_matches_question_and_review_interactions_by_parent_id` | **Real bug, with a history (Stage 8 correction).** `bd64666` (Sep 12) had `question`/`review` in `_INTERACTION_TYPE_MAP`; `b4a6a79` (Sep 19) added the parent-id lookup and this test, which passed; later the same day `5d239e2` ("62 adversarial audit findings") deliberately moved both types to `_CONTENT_TYPE_MAP` and removed them from the interaction map — making StackExchange questions and Amazon/App Store reviews standalone content, but breaking `b4a6a79`'s test and leaving `_find_content_item_for_interaction`'s comment stale. Both earlier positions were half right. | `collector.py` now holds both: a `parent_id` decides. This **reverses part of `5d239e2`** for the parented case only. |

## Decision

- **Collector.** `question`/`review` are added to `_INTERACTION_TYPE_MAP`.
  Because they are also (deliberately) in `_CONTENT_TYPE_MAP` — a
  StackExchange question or an Amazon/App Store review with no parent is
  standalone content — a new `_is_interaction(item)` makes the split: a
  type in both maps is an interaction **iff** it carries a `parent_id`;
  `_persist_items` classifies with it so no item is persisted twice. New
  test `test_standalone_question_and_review_remain_content_items` pins the
  unparented case (THREAD/ARTICLE content, zero interactions).
- **yt-dlp.** `types-yt-dlp` added to the dev extras; the `yt_dlp.*` mypy
  override removed. The stubs type `extract_info` with extra optional
  parameters and a TypedDict return, which does not structurally satisfy
  the adapter's narrow `_Extractor` protocol; `_default_factory` now uses
  an explicit `cast(_Extractor, …)` with a comment, replacing the previous
  `# type: ignore[no-any-return]` (which the stubs made "unused").
- **Deselect list.** Empty. The full suite is now run with no exclusions.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/acquisition/collector.py` | `question`/`review` in `_INTERACTION_TYPE_MAP`; `_is_interaction`; classification in `_persist_items` |
| `corp/workers/adapters/ytdlp.py` | `cast` instead of `type: ignore` |
| `pyproject.toml` | `types-yt-dlp` in dev extras; `yt_dlp.*` override removed |
| `tests/integration/test_collector.py` | New standalone question/review test |
| `tests/integration/test_dossier_pipeline.py` | Renamed-method fix + ordering assertion |
| `tests/conftest.py` | Autouse `_fresh_app_engine` fixture (see e2e triage) |

No migration. No model changes. The collector change IS a behaviour change
(parented questions/reviews become interactions), which is what the
existing test, the enum, and the lookup code always specified.

## Verification

- `python -m ruff check`: clean. `python -m mypy corp --strict`: clean, 138
  files, with the `yt_dlp` override gone.
- `tests/integration/test_collector.py` + `test_dossier_pipeline.py` +
  `tests/workers/test_ytdlp_adapter.py` + `test_campaign_pipeline_e2e.py`:
  41 passed (before the standalone test was added); collector + the three
  adapters that emit `question`/`review` (StackExchange, Amazon reviews,
  App Store) + e2e + niche discovery: 79 passed.
- Ordering repro: `tests/api` + e2e failed (1 failed, 93 passed) before the
  conftest fixture and passes after it (94 passed); `tests/workers` + e2e
  and `tests/core tests/warmstore` + e2e passed both before and after.
- Full suite, **no deselects**, `python -m pytest tests/ -q`:
  **1287 passed, 1 skipped, 0 failed** — the first fully green run of the
  suite since this plan began.

## Consequences

- A question/review that carries a `parent_id` is persisted as an
  `AudienceInteraction` (QUESTION/REVIEW) rather than as content. **Today
  this is correct-but-latent**: no shipped adapter emits a parented
  question or review (`stackexchange.py` questions have no parent and its
  answers are `reply`; `amazonreviews.py`/`appstore.py` set none), so the
  only observable change is the test. The first adapter that does (e.g. a
  YouTube Q&A or a product-page review thread) gets the right behaviour
  without touching the collector. Standalone questions/reviews keep
  `5d239e2`'s THREAD/ARTICLE handling, pinned by the new test.
- The "known pre-existing failures" caveat disappears from future ADRs.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` remains untracked at the repo root.
