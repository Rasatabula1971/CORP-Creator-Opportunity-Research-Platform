# FAIR as an in-process provider; prompts carry their answer schema

**Status:** ACCEPTED (2026-09-15)
**Date:** 2026-09-14
**Trigger:** The FAIR provider wired in commit `6d97556` was an HTTP client for
`FAIR_URL/v1/solve`. FAIR has since removed its server layer (FAIR `ac61429`) and
become an embeddable library, so that adapter targeted an endpoint that no longer
exists — harmless only because `FAIR_URL` was never set. Separately, FAIR's quality
gate only accepted answers it could verify, which ruled out open-ended extraction
(`docs/DECISIONS/0008`, "investigated and rejected"). FAIR PR #6 adds a
schema-validated tier that lifts that restriction. With both changed, FAIR is the
natural home for provider routing: CORP's pool governs two members; FAIR governs
every free provider it holds a key for — **nine providers, twenty models** on this
machine — and judges each answer.

## What shipped

- `corp/workers/providers/fair.py` — rewritten. `FairProvider` wraps a
  `fair.embedded.module.FAIR` instance (duck-typed; tests use a fake). Each call
  becomes `solve(task, expected_schema=…)`; an `ACCEPTED` answer is parsed
  (markdown fences stripped) and attributed to the member that answered. FAIR's
  verdicts map onto the pool's error vocabulary so a FAIR provider could sit inside
  a `PooledProvider`: every attempt quota-blocked → `ProviderExhaustedError`
  (`daily` when all were `QUOTA_EXHAUSTED`; a 60 s `retry_after` when any was
  `RATE_LIMITED`); members unreachable or FAIR's validator down →
  `ProviderUnavailableError`; answers came back but none passed quality →
  `ProviderError` (about the prompt, not the provider's health). Provenance
  surface identical to the pool: `model_name` (last answering model, in the
  vendor-canonical label the bare providers use — `gemini-3.6-flash`,
  `groq/openai/gpt-oss-20b`, `mistral/…`), `models_used()`, `member_names()` (every
  routable model = one idempotency family, shared with the pool's). `build_fair_provider(cfg)` does the lazy
  import; `fair_available()` is the install check.
- `LLMProvider.generate_json(prompt, system=None, *, schema=None)` — every
  provider takes the JSON Schema of the expected answer. FAIR verifies against it;
  Gemini and Groq accept and ignore it (JSON mode + prompt, as before); the pool
  passes it through. The four prompt helpers (`extraction`, `creator_content`,
  `topics`, `intent`) each declare a schema next to their prompt version, in the
  strict-mode shape every provider's structured-output mode accepts (all properties
  required, no extras). The parsers keep their defaults for providers that only see
  the prompt. Every call also sends `task_type="extraction"`.
- `corp/workers/providers/factory.py` — `LLM_PROVIDER=auto` prefers FAIR when the
  package is installed, `FAIR_ENABLED` is true and FAIR finds at least one provider
  key; otherwise (or if FAIR is unusable, logged) it falls through to the pool as
  before. `LLM_PROVIDER=fair` demands it.
- Settings: `FAIR_URL`/`FAIR_API_KEY` removed; `FAIR_ENABLED` (true),
  `FAIR_ENV_FILE` (FAIR's own `.env`, where the other providers' keys live),
  `FAIR_MAX_OUTPUT_TOKENS` (2048), `FAIR_CACHE_ENABLED` (true) added;
  `FAIR_CLIENT_ID`, `FAIR_QUALITY_LEVEL`, `FAIR_PRIORITY`, `FAIR_TIMEOUT_SECONDS`
  kept. CORP hands FAIR its own `GEMINI_API_KEY`/`GROQ_API_KEY` too.
- Tests: `tests/workers/test_fair_provider.py` rewritten against a fake router
  (22 tests: attribution, fence stripping, provenance accumulation, every verdict
  mapping, bad-but-accepted output, `solve()` raising). Factory tests reworked
  with `no_fair` / `fake_fair` fixtures (FAIR preferred, disabled, unusable →
  fallback, explicit). Thirteen fake providers across the test suite accept the
  new keyword.

## Problems found by the first live run (#7) and fixed

Run #7 (`intelligence` on the Veritasium creator) was stopped after 9 calls: 1
accepted, 8 escalated, and it was re-extracting items the pool had already done.
Stopped by hand; the transaction rolled back, nothing persisted. Three causes:

1. **Idempotency family split by route.** The first version labelled answers
   `fair/<provider>/<model>`. `_already_extracted` matches on the provider's
   `member_names()`, and none of those matched the 399 observations recorded as
   `groq/openai/gpt-oss-20b` by the pool — so FAIR started re-extracting everything.
   Provenance names the *model*, not the route: labels are now vendor-canonical
   (`gemini-3.6-flash`, `groq/openai/gpt-oss-20b`, `mistral/ministral-8b-latest`),
   the same strings the bare providers record; the route is on the run
   (`model_versions.primary = "fair-router"`). Work done via the pool and via FAIR
   is one family.
2. **FAIR's task profiler classified the data, not the request.** It inferred a
   *coding* requirement from `code|python|…` and a *grounding* requirement from
   `sources|research|latest|…` anywhere in the task text — which for CORP includes
   the comment or video description being analysed. 5 of the 13 outstanding
   Veritasium items tripped one (descriptions with a "Sources" section, "code" in
   sponsor text) and escalated as `QUALITY_VERIFICATION_UNAVAILABLE` /
   `GROUNDING_REQUIRED`. Fixed upstream: FAIR PR #7 runs keyword inference only
   when the caller gave no `task_type`; CORP now sends `task_type="extraction"`.
3. **Groq rejected FAIR's strict `json_schema` request** (400: "`additionalProperties:
   false` must be set on every object", then "`required` must list every key in
   `properties`"). FAIR maps a 400 to `PROVIDER_UNAVAILABLE`, so every Groq attempt
   failed and its governor sidelined Groq. Fixed in CORP: the four schemas are now
   strict-mode shapes — every object lists all its properties as required and forbids
   extras. Verified directly against Groq for all three shapes (200, conformant JSON).
   The parsers keep their defaults for providers that only see the prompt. Trade-off:
   a model that omits a field now fails FAIR's check instead of getting the default —
   which strict-mode providers cannot do by construction, and Gemini receives the
   same schema as `responseJsonSchema`.

## Install

FAIR is not on PyPI. It is installed editable from its repo into CORP's venv:

    pip install -e "C:\FAIR Free AI Router"

FAIR PRs #6 (schema tier), #7 (explicit task_type) and #8 (Groq cooldown, Mistral
model refresh) are all merged; CORP's venv is installed editable from the main FAIR
checkout at `origin/codex/sprint-b-quality` `f4e58a7`. **CORP needs #6 and #7**:
without #6 every answer is `UNVERIFIED`; without #7 items whose text mentions "code"
or "sources" escalate. Re-verified on this state: FAIR's own suite, CORP's FAIR/factory
tests, and a live call whose comment text mentions "python" and "sources" — accepted,
`STRUCTURE_VALIDATED`.

## Verification

- Non-DB suite: 293 passed (280 before this slice). DB integration suite: 100 passed, 1 skipped,
  1 setup ERROR in `test_pipeline_failure_marks_run_failed` whose traceback was lost;
  the file re-run alone passes 6/6, so it is taken as a transient Supabase connection
  hiccup during the 8.5-minute run, not a code failure. ruff clean on every changed file; mypy adds no findings;
  import-linter 2 kept.
- **Live, single call**: FAIR built with 9 providers / 20 models from `FAIR_ENV_FILE`;
  an extraction prompt with `EXTRACTION_SCHEMA` answered by
  `google_gemini_api/gemini-3.5-flash-lite`, `STRUCTURE_VALIDATED`.
- **Live, runs #8 and #9** (`intelligence` on the Veritasium creator, after the three
  fixes above): #8 `completed` — 12 ok / 2 failed / 37 skipped, members used
  `gemini-3.5-flash-lite` and `cloudflare_workers_ai/llama-3.3-70b`; the 2 failures
  were the Groq strict-schema 400 (fixed after). #9 `completed` — 5 ok / 0 failed /
  46 skipped. Every one of the 13 items the pool could not finish under Groq's token
  budget now has creator-side observations (51 new, labelled `gemini-3.5-flash-lite`);
  the 399 done by the pool were skipped, not redone; zero duplicate observations.
  `model_versions` on both runs: `primary: fair-router`, `used: [...]`.
- Not one of the nine runs so far has touched a paid provider; FAIR's registry only
  admits free access classes.

## Noted

- FAIR's per-provider `request_limit` for Gemini is the generic 1500, not this
  key's 20. FAIR marks the provider exhausted from the 429 headers anyway; the
  cost is one wasted call per day. Not changed here.
- FAIR's `cache_enabled` returns the cached answer for an identical task. CORP's
  prompts embed the comment text, so a true repeat is a re-run of the same item —
  which idempotency already skips before the call. Harmless; left on.
- `PooledProvider` is kept: it is the fallback when FAIR is not installed, and
  `LLM_PROVIDER=pool` still works. A FAIR member inside a pool is possible (the
  error mapping is for that) but not wired — FAIR already is the pool.
