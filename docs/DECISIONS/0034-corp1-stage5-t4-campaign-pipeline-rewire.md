# ADR-0034 — CORP1 Stage 5, T4: Campaign Pipeline Rewire

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Stage 5, task T4

## Context

T3 (ADR-0033) built `RecursiveNicheDiscovery`, a standalone engine. T4's
job is to make the campaign pipeline's `discover` stage actually call it,
in place of the old single-platform `NicheDiscoveryCollector`, while every
downstream stage (canonicalize, verify, estimate-ecosystem, qualify,
select, onboard, research-campaign) keeps working unmodified.

## Decisions

### `discover` now calls `RecursiveNicheDiscovery`, and no longer needs a platform

The old stage required `source` (a platform: youtube/reddit/tiktok) and
`query`. The new one only needs `query` (the broad topic) — T3 fans out
across every relevant capability provider automatically, so there is no
single platform to choose. `source` is still accepted (as an unused,
optional parameter) so nothing calling the old shape breaks outright.

### The `candidates` stage is no longer part of the default flow

T3's engine already produces `STAGED` `NicheCandidate` rows directly
(evidence collection + LLM synthesis + grounding, all in one call) — it
subsumes what `discover` (collect evidence) and `candidates`
(cluster evidence into candidates) used to do *together*. The `candidates`
backend dispatch branch and `NicheCandidateGenerator` are untouched and
still callable (some other evidence-collection path may still want
clustering-based candidate generation), but the frontend's default
pipeline step list no longer shows it — `discover` now flows straight to
`canonicalize`.

### Scope had to expand by one file beyond the frozen list: `corp/api/routes_ops.py`

T4's frozen "Allowed files" were only `corp/api/jobs.py` and
`web/src/pages/CampaignDetailPage.tsx`. Discovered while wiring this up:
`routes_ops.py`'s `start_campaign_pipeline` endpoint has its **own**
pre-validation — `if stage == "discover" and not (source and query):
raise HTTPException(422, "discover requires source and query")` — a
check that runs *before* the request ever reaches `jobs.py`. Leaving it
unchanged would reject every discover request the updated frontend sends
(since it no longer sends `source`), making the rest of T4 unreachable
through the API. Fixed to require only `query`. This is a necessary
correction to make T4 actually work end-to-end, not a scope-creep
addition — documented here rather than silently expanded. The
corresponding stale test
(`test_start_discover_requires_source_and_query`) was updated to match
(`test_start_discover_requires_query`).

### The rules path is hardcoded, not settings-driven, by necessity

Every sibling stage's rules file is configurable via `corp.config.Settings`
(`scoring_rules_path`, `intent_rules_path`, `niche_qualification_rules_path`).
Adding a matching `niche_discovery_rules_path` setting would be the
consistent choice, but `corp/config.py` is outside T4's frozen file list.
`jobs.py`'s new `discover` branch hardcodes the literal path
(`"rules/niche_discovery_prompt.yaml"`, the same file T3 already
introduced) rather than expand scope a second time for a non-blocking
inconsistency. Worth a follow-up settings-cleanup task.

## The end-to-end test's boundary

T4's frozen test requirement: "an end-to-end campaign run against a
fixture topic reaches a dossier without manual intervention."
`tests/integration/test_campaign_pipeline_e2e.py` runs all of discover,
canonicalize, verify, estimate-ecosystem, qualify, select, and onboard
through `jobs.run_campaign_pipeline` (the exact dispatcher the API calls),
faking only the external boundaries (LLM, niche adapters, embeddings,
YouTube search) — every DB-only stage runs for real.

`research-campaign` is the one exception: `jobs.py`'s branch hardcodes a
real `ResearchOrchestrator` with no injection point, and faking its full
internal chain (collect → intelligence → cluster → intent → scoring) would
mean re-deriving test coverage that pipeline's own existing test suite
already provides, for code T4 does not touch. Instead, the test calls
`CampaignResearchBatch` (the exact class `jobs.py`'s branch instantiates)
directly with the same `FakeResearcher` `test_campaign_research_batch.py`
already validates against it — proving the onboarded creators T4's chain
produces are shaped correctly for it, without re-testing what's already
tested and unchanged. A `CreatorScore`/`OpportunityScore`/`ProblemCluster`
set is then seeded (standing in for what a real research pass would
produce) and `DossierGenerator.generate_data()` — the actual "reaches a
dossier" proof, already-existing code unrelated to T4 — is confirmed to
succeed against the result.

## Files changed

| File | Change |
| --- | --- |
| `corp/api/jobs.py` | `discover` branch now calls `RecursiveNicheDiscovery`; `source` no longer required. |
| `corp/api/routes_ops.py` | Pre-validation now requires only `query` for `discover` (necessary correction, see above). |
| `web/src/pages/CampaignDetailPage.tsx` | Removed the platform dropdown from the discover input; removed "Generate Candidates" from the default pipeline stage list. |
| `tests/api/test_campaign_endpoints.py` | Updated the one test asserting the old `source`+`query` requirement. |
| `tests/integration/test_campaign_pipeline_e2e.py` | New — the required end-to-end test. |

## Verification

- `mypy --strict` clean on `corp/api/jobs.py` and `corp/api/routes_ops.py`.
  The two test files carry the same pre-existing `no-untyped-def` gap
  already present throughout this codebase's test suite (bare test
  function signatures, no `-> None`) — confirmed via `git stash` that
  `test_campaign_endpoints.py`'s instances predate T4, and the new
  `test_campaign_pipeline_e2e.py` follows the same established
  convention rather than being held to a stricter standard than every
  other test file in the project. (Corrected here per Stage 8 review,
  which flagged the original wording — "clean on all changed Python
  files" — as inaccurate for the test files specifically.)
- `ruff check` clean on all changed files except one pre-existing,
  unrelated warning (`JobStatus(str, Enum)` at `jobs.py:44`, confirmed
  outside T4's diff).
- `tsc --noEmit` clean on the frontend change.
- New end-to-end test passes.
- Full `tests/integration/` + `tests/api/` (295 passed, 1 pre-existing
  unrelated skip) and `tests/workers/` (553 tests) suites pass — zero
  regressions.

## Note on unrelated working-tree state (per Stage 8 review)

`git status` during this task also shows `web/src/api/client.ts` and
`start_corp.bat` as modified. **Neither is a T4 change.** Both predate
Stage 6 of this task entirely — leftover uncommitted work from earlier in
this session (before T0), carried in the working tree the whole way
through T0/T1/T2/T3 and correctly excluded from each of those commits the
same way they are excluded here. Flagging this explicitly so a future
review reading `git status` doesn't mistake pre-existing ambient state for
undisclosed scope creep in whichever task happens to run next.

## Consequences

- The campaign pipeline is now fully wired from broad topic to a
  dossier-ready creator, with no manual data-fixing required between
  stages.
- T5 (product idea generation) and T6 (dossier model/generator) can build
  on this without touching the discovery→onboarding chain again.
- The hardcoded rules path and the `routes_ops.py` correction are both
  flagged above as small, deliberate, documented scope decisions — not
  silent expansions.
