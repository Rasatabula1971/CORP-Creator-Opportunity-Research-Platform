# ADR-0042 — CORP1 Stage 5, T13: Kickstarter + Indiegogo Adapter (Phase 2.3)

**Status:** Accepted (pending Stage 8/9)
**Date:** 2026-09-18
**Reference:** CORP1 Product Spec & Build Plan, Phase 2.3 "Kickstarter
and Indiegogo Adapter" and Stage 5, T11–T15 ("Phase 2 adapters" template)

## Context

Same shared adapter-task template as T11/T12: one new file under
`corp/workers/adapters/`, no changes to any other adapter or the
scoring engine, no migration, a conformance test plus a "live-fixture
test" for the evidence fields named. **T11 (Pinterest) and T12 (Google
Search) have no ADR in this repo** — both were paused before ever
reaching a Stage 9/10 commit (this project only writes an ADR for a
task once it's accepted and committed, per the established convention),
so their build attempts, the reasoning for pausing them, and the
discarded draft code are recorded only in durable memory (the
`corp-vision` and `feedback-adr-driven-workflow` memory files), not as
a numbered ADR — hence the gap from 0040 straight to 0042. Stage 8
review of this task flagged an earlier draft of this paragraph citing a
nonexistent "ADR-0041"; fixed here.

Phase 2.3: capability `TransactionProvider`. "Why it matters": "Someone
backing a Kickstarter project has demonstrated the strongest form of
commercial intent — they paid money for something that does not exist
yet. This is the most powerful demand signal available." Collects:
projects in the niche category, funding amounts and backer counts,
project descriptions and categories, comments and community engagement,
success and failure rates.

**Applying the standing practice established after T11/T12 (see
`feedback-adr-driven-workflow` memory): the real Kickstarter and
Indiegogo sites were checked live with the built-in browser before
writing any code** — navigating to real search pages, reading actual
captured network responses, and testing candidate request parameters
directly against the live endpoints, rather than assuming a shape from
a similar adapter's pattern. Unlike T11 (Pinterest) and T12 (Google
Search), this check confirmed both platforms have real, working,
unauthenticated public data sources — this task was buildable, not
blocked.

## Decisions

### Kickstarter: `GET /discover/advanced.json`

Confirmed live: `?term=<query>&sort=magic&state[]=successful&
state[]=failed&state[]=live` returns a clean `projects` array with
`name`, `blurb`, `goal`, `pledged`, `backers_count`, `category.name`,
`state`, `percent_funded`, `currency`, `launched_at`, and a project URL
— directly. No auth. Covers four of the five "what it collects" items
in a single call: project descriptions/categories, funding amounts and
backer counts, and (via `state`, aggregatable) success/failure rates.

### Indiegogo: `POST /api/projectSearch/searchProjects`

Confirmed live by testing candidate parameter names directly against
the real endpoint: `query`/`q`/`keywords`/`searchTerm`/`searchQuery`/
`text` all silently returned unfiltered global results (10,000+ hits,
unrelated projects) instead of erroring — only `{"term": <query>,
"pageIndex": 0, "pageSize": <n>}` actually filters. Returns `name`,
`shortDescription`, `catalogCategory` (numeric), `campaignOutcome`
(numeric), `publishedDate`, and a project URL.

**Two disclosed gaps, not silently dropped:**
- **Funding amount and backer count are NOT in this response.**
  Verified directly: a live Indiegogo project page renders "147 backers
  raised" as text, but that number is server-rendered into the
  individual project's HTML page, not exposed by the search-list JSON
  endpoint. Getting it would need one extra page fetch per project (a
  bounded N+1, the same shape `AmazonReviewAdapter` already uses for
  product → reviews) — deferred rather than built now, to keep this
  first version to one call per platform per query. Kickstarter's
  response covers this requirement directly, so the capability isn't
  entirely unmet — just not from Indiegogo yet.
- `catalogCategory`/`campaignOutcome` are stored as **raw numeric
  values** in metadata (`catalog_category_id`, `campaign_outcome_raw`),
  not translated to a label. The samples checked during verification
  weren't enough to confidently confirm what each numeric value means
  (e.g. whether `campaignOutcome: 1` reliably means "successful") —
  asserting an unverified mapping would be worse than an honest raw
  number.

### Comments/community engagement: not implemented, disclosed

Kickstarter's discussion/comment data lives behind its GraphQL API
(`POST /graph`), observed live but not reverse-engineered — GraphQL
endpoints typically need persisted-query hashes or operation names that
aren't derivable from a network trace alone, and are far more fragile
to depend on than the plain JSON/REST endpoints both platforms' search
already provides. This is the one "what it collects" item genuinely not
covered by either platform in this version — flagged explicitly rather
than worked around with a guess.

### One adapter, umbrella platform name — mirrors `MarketplaceAdapter`

`CrowdfundingAdapter(SourceAdapter, TransactionProvider)` follows
`MarketplaceAdapter`'s exact established pattern for one adapter file
covering multiple sites: `platform`/`source_platform` = `"crowdfunding"`
(not "kickstarter"/"indiegogo" individually), with
`metadata["platform"]` distinguishing the site; `kickstarter:`/
`indiegogo:` identifier prefixes plus a bare-query fan-out to both;
per-platform failure isolation (one site failing doesn't discard
results already gathered from the other, only raises if *both* fail
with nothing collected) — copied from `MarketplaceAdapter._collect_all`
unchanged in structure.

## Files changed

| File | Change |
| --- | --- |
| `corp/workers/adapters/crowdfunding.py` (new) | `CrowdfundingAdapter`, `_parse_kickstarter_response()`, `_parse_indiegogo_response()`, `_parse_indiegogo_date()`. |
| `corp/workers/adapters/registry.py` | New `if name == "crowdfunding":` branch; `"crowdfunding"` added to `KNOWN_PLATFORMS`. |
| `corp/config.py` | New `crowdfunding_max_projects` setting. |
| `tests/workers/test_crowdfunding_adapter.py` (new) | 16 tests: adapter properties, Kickstarter/Indiegogo response parsing (using fixtures trimmed from the real captures made while verifying live, not invented), date parsing, `collect()` via mocked HTTP for each platform prefix and the bare-query fan-out, per-platform failure isolation, both-fail raises, max-projects cap, request counting, `close()`, one conformance test for `TransactionProvider`. |

No changes to any other adapter file or to `rules/scoring.yaml`.

## Stage 8 review: ACCEPT, one dangling-citation fix applied

Independent review confirmed the `MarketplaceAdapter._collect_all`
mirroring is genuine (checked against that pattern's own git history,
not just structural resemblance), the disclosed gaps (comments not
collected; Indiegogo funding/backers not collected; `catalogCategory`/
`campaignOutcome` left as raw, unverified numeric values) hold exactly
— nothing anywhere in the codebase silently translates the raw
Indiegogo outcome codes into a confident label — and per-item test
coverage of the five "what it collects" fields tracks the disclosed
capability/gap boundary precisely, with no over- or under-claiming. All
tool/test runs matched the ADR's numbers exactly. One required fix,
applied above: the Context section cited a nonexistent "ADR-0041" for
the T11/T12 narrative — corrected to explain why no such file exists
(both tasks were paused before reaching a Stage 10 commit, so per this
project's own convention no ADR was ever written for them; their record
lives in durable memory instead). One minor, non-blocking note: a
missing `id`/`projectID` on either platform's response would collapse
`stable_id`'s dedup key to a shared `"None"` suffix — low-probability
given both are core fields on a live API response, not fixed here.

## Verification

- `mypy --strict` and `ruff check` clean on `crowdfunding.py`, the registry/config companion changes, and the test file.
- `python -c "build_adapter('crowdfunding')"` confirmed live: returns a `CrowdfundingAdapter` with `family=NICHE`, `access_method=OPEN`, `compliance_status=VERIFY`.
- `tests/workers/test_crowdfunding_adapter.py`: 16 passed.
- Full `tests/workers/`: 591 passed (up from 575, the 16 new tests), zero failures.
- Full `tests/integration/` + `tests/api/`: 346 passed, 1 pre-existing
  unrelated skip — unchanged from T10's baseline, confirming the
  registry/config companion changes introduced zero regressions.

## Consequences

- A follow-up task could add the bounded per-project fetch for
  Indiegogo funding/backer figures, and/or reverse-engineer Kickstarter's
  GraphQL comment counts, without touching this file's core structure —
  both are additive, not a rework.
- T14/T15 (Patreon/Substack, Quora — the remaining Phase 2 adapters) should
  apply the same live-verification practice before writing any code.

## Note on unrelated working-tree state

`git status` shows `start_corp.bat` and `web/src/api/client.ts` modified,
plus an untracked PDF, none of which T13 touched — the same pre-existing
dev-environment changes disclosed in every ADR since T4. Not staged as
part of this task's commit.
