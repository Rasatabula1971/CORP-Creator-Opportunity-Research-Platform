# Provider pool: Gemini daily cap + Groq failover

**Status:** ACCEPTED (2026-09-14)
**Date:** 2026-09-14
**Trigger:** Gemini's free tier on this key is 20 requests/day on `gemini-3.6-flash` (every
older model returns "no longer available to new users"). Slice 8 brings the LLM back
into the pipeline, so this had to be solved first.

## What shipped

- `corp/workers/providers/errors.py` — two health signals the pool acts on:
  `ProviderExhaustedError` (quota; carries `retry_after` and a `daily` flag) and
  `ProviderUnavailableError` (transient, retries exhausted). Anything else a provider
  raises is call-specific and never triggers failover.
- `corp/workers/providers/groq.py` — `GroqProvider`, OpenAI-compatible chat
  completions in `json_object` mode (the same "just return JSON" contract Gemini uses).
  Verified free tier: 1000 requests per rolling day, 8,000 tokens per minute.
- `corp/workers/providers/pool.py` — `PooledProvider`, same `LLMProvider` interface
  (no pipeline changes). Tries members in order; cools down one that reports
  exhaustion (its own `retry-after`, or `LLM_COOLDOWN_SECONDS` for a daily cap) or a
  transient outage; when *no* member is available, waits for the soonest cooldown to
  expire up to `LLM_MAX_WAIT_SECONDS`, then fails. Reports the model that actually
  answered (`model_name`), the set that answered during its life (`models_used()`),
  and its member names for idempotency (`member_names()`).
- `corp/workers/providers/registry.py` — Gemini: 429s are no longer retried inside the
  call; they are classified (`GenerateRequestsPerDay…` ⇒ daily, `…PerMinute…` ⇒ short,
  with the "retry in Ns" hint honoured only for the latter) and raised for the pool.
  Transient 503/504 keep a short retry.
- `corp/workers/providers/factory.py` — `LLM_PROVIDER=auto` pools every configured key
  in `LLM_PROVIDER_ORDER` (default `gemini,groq`); one key ⇒ bare provider (existing
  behaviour preserved); explicit `groq` and `pool` choices added.
- Pipelines (`pipeline.py`, `intent_pipeline.py`) — two provenance fixes the pool made
  necessary: the idempotency skip now matches any pool member's model name (so a
  re-run does not re-extract items done by a different member), and each run records
  `model_versions.used` at finish alongside the `primary` captured at start.
- Settings: `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_TIMEOUT_SECONDS`, `GROQ_MAX_OUTPUT_TOKENS`
  (2048), `GROQ_REASONING_EFFORT` (`low`), `LLM_PROVIDER_ORDER`, `LLM_COOLDOWN_SECONDS`
  (3600), `LLM_MAX_WAIT_SECONDS` (300).

## Investigated and rejected

FAIR's `solve()`: its quality gate only ACCEPTs answers it can independently verify
(arithmetic, reference match, grounded citations, code tests). Open-ended extraction
has no ground truth, so it can never be ACCEPTED there. Two real bugs were fixed in
FAIR along the way (stale Groq model ids; `additionalProperties: false` required by
Groq's strict schema mode) but the verification gate is a design mismatch, not a bug.

## Problems found live, in order, and what each changed

Verified against the real dev database on the Veritasium creator (50 content items).
Every pipeline run below is a real `research_runs` row unless stated.

1. **Instant-fail cascade (run #2, 50/51 failed in 39 s).** Gemini daily-capped
   (correct). One Groq per-minute 429 cooled Groq for its short `retry-after`; then
   every remaining call found both members cooling and failed at once ("last errors:
   none this call"). Fix: when nobody is available, the pool **waits** for the soonest
   expiry if it is within `max_wait_seconds`. Test pins it.

2. **`json_validate_failed` 400s (27 of 50 creator-extraction calls, run #2 after the
   wait fix, 931 s).** Reproduced on three real failed items; Groq's own text from a
   later probe: *"max completion tokens reached before generating a valid document."*
   gpt-oss-20b is a reasoning model; at default effort it spent ~500 reasoning tokens
   per call and, on some inputs, exhausted the completion budget before valid JSON.
   Fix: `reasoning_effort="low"` (measured 16–100 reasoning tokens) plus an explicit
   `max_completion_tokens`. All three failing items then succeeded (11, 9, 8
   observations). Run #3: the 400s were gone; 13 more items extracted; 175 s.
   Tradeoff: on a synthetic prompt low effort produced 6 observations vs 7; the setting
   is configurable.

3. **A 159 s `retry-after` exceeded a 90 s max wait (run #3, 15/28 failed).** Groq's
   token bucket asked for a longer refill than the per-minute hints seen earlier. For a
   batch pipeline, waiting beats failing every remaining unit. Fix: default
   `LLM_MAX_WAIT_SECONDS=300`, exposed as a setting. Test pins the 159 s case.

4. **Misclassified "daily cap" (run #4, 14/15 failed in 23 s).** My Groq classifier
   inferred *daily* from `retry_after > 300`, cooling Groq for an hour on a stall that
   a header probe showed had cleared within minutes (922/1000 requests and a full
   per-minute token bucket remaining). Fix: never infer "daily" from the size of the
   wait — honour Groq's own `retry-after` and reserve `daily` for
   `x-ratelimit-remaining-requests: 0`; the pool's max wait makes the wait/fail call.
   The 429 message now carries remaining requests/tokens for diagnosis. Also:
   `max_completion_tokens` is reserved against the 8k/min bucket, so 4096 throttled to
   ~1 call/min; measured completions stay under 500 tokens, default is now 2048.

5. **A genuine 836 s stall, then a vanished run (run #5).** With the honest classifier,
   Groq reported a ~14-minute token-budget stall (after ~350 calls that day). The pool
   correctly refused to wait that long under a 300 s bound. But because Groq was
   stalled from the first call, *every* unit failed, `finish_run` raised
   `PipelineFailureError`, the CLI never committed, and the run row was rolled back —
   research memory lost. This is the **pre-existing** flaw flagged in
   `docs/DECISIONS/0007`, now hit repeatedly. It also breaks Slice 7's "`discover()`
   never raises" contract in the all-items-fail case. **Not fixed here**: it changes
   every pipeline's contract (`finish_run` should return a status, callers and the
   orchestrator should read it) and deserves its own gate.

6. **Run #6, `LLM_MAX_WAIT_SECONDS=900`: stopped after 43 minutes.** Launched to ride
   out the stall and finish the last 13 items. The arithmetic I should have done first:
   Groq's daily token budget refills slowly, so the pattern was *sleep ~14 min → one
   call succeeds → next call gets another ~14 min retry-after* — roughly three hours
   for a status line, holding a transaction open the whole time, with every success
   lost if anything killed it before the final commit. Stopped deliberately; the
   transaction rolled back, nothing lost. Lesson: a long max wait is right for a
   *single* stall, wrong for a *budget* that refills slower than the pipeline
   consumes it. The remaining 13 items complete in ~3 minutes once the daily token
   budget resets (run #3's rate), and idempotency makes that re-run free.

## What the live runs prove

- Gemini's daily cap ⇒ one wasted attempt, then Groq for everything: 399 creator-side
  observations and 50 topic classifications produced under the cap that previously
  stopped the pipeline at the first call.
- Per-observation `model_version` and run-level `model_versions.used` both record the
  member that actually answered.
- Idempotency across runs: 36 done items skipped in run #4, zero duplicate
  observations across five runs.
- The remaining constraint is Groq's *token* budget, not requests: ~8k/min and a daily
  allowance this session largely spent on run #2's default-effort prompts.

## Open items

- Make `finish_run` return a status instead of raising (see 5). Done in
  `docs/DECISIONS/0009`, gated separately.
- Pipelines burst calls back-to-back; a small pacing delay (or an early stop when the
  pool reports exhaustion) would turn "wait out the bucket" stalls into steady
  throughput. Out of scope here.
- Gemini's classifier is message-based; if Google changes the quota-id wording the
  daily/minute split degrades to "short wait", which the pool tolerates.
