# Slice 7 — Niche Discovery Light: One Source

**Status:** ACCEPTED
**Date:** 2026-09-14
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`, Slice 7 / §15 Stage A / §24

## What shipped

`NicheDiscoveryCollector` (`corp/workers/acquisition/discovery.py`): one query against
one adapter, under a campaign. It creates a `NICHE_DISCOVERY` `ResearchRun`
(`scope=niche`, `campaign_id` set, no creator, no niche), persists every result as
append-only `Evidence` linked to that run, deduplicates against evidence already held
(same platform + source id), records the query and its yield in the Slice 6 ledger,
and archives the raw normalized items as JSONL under `CORP_DATA_PATH` (§24), storing
only a data-path-relative reference in the database.

Reuse, not rebuild: the existing adapter contract, `Evidence` as-is, the shared
`start_run`/`finish_run`/`fail_run` lifecycle (extended with optional
`run_type`/`campaign_id`/`niche_id` kwargs that default to prior behavior), the
Slice 5 `validate_run_type` helper, and the Slice 6 ledger. No LLM call anywhere.

Also: `CORP_DATA_PATH` setting (default `corp_data`, gitignored), and two CLI
commands — `add-campaign <name>` and `discover <campaign_id> <source> <query>` — so a
person can start a discovery run, which is the first acceptance criterion.

## Live verification (real dev database, real source)

Run 1, `discover <campaign> youtube "ytsearch3:espresso machine leaking from group head"`:
run `completed`, ledger `SUCCEEDED` seen=3 new=3 dup=0, three `video` evidence rows
from three different channels (Paul Longer, Brew Coffee Home, Casabrews — a genuine
cross-creator ecosystem signal, not one creator's feed), tagged `OPEN`/`VERIFY`,
provenance traced evidence → run → campaign name, JSONL archive on disk with three
lines.

Run 2, same query 73 s later: run `completed`, seen=3 new=0 dup=3, evidence total
unchanged at 3, ledger now holds two rows for the query with distinct `executed_at`
and the yield falling 3 → 0. That is invariant 8 (no blind re-research) and §13
query memory working against a live source.

## Problems found during this slice

### 1. Reddit's unauthenticated `.json` feed is blocked (external)

The first live attempt used the Reddit adapter (`r/espresso`). Reddit returned
`403 Blocked` on `/r/espresso/new.json`. The adapter had only ever run against a
mocked transport; this was its first live call. Reddit tightened unauthenticated
access to these endpoints some time ago, and the descriptive User-Agent this adapter
sends (per Reddit's own API rules) is evidently not enough.

Not worked around. Spoofing a browser UA or routing via `old.reddit.com` would be
detection evasion, contrary to this project's non-evasive-sources stance. The
honest path to Reddit is a free OAuth "script" app (client id/secret), which is a
user action — and commercial use still needs Reddit's approval, which is why the
adapter already tags evidence `VERIFY`. Recorded as an open item; the adapter is
unchanged.

### 2. A failed search was persisted and then rolled back (mine)

The collector correctly wrote the FAILED ledger row and marked the run failed, then
re-raised — so the CLI's `session.commit()` never ran and both rows were discarded.
Observed live in the Reddit attempt: `INSERT research_runs`, `INSERT
research_queries (... 'FAILED', '403 Blocked ...')`, `UPDATE research_runs SET
status='failed'`, `ROLLBACK`. For a ledger whose purpose is "has this been tried and
what happened?", losing failures defeats it.

Fix: `discover()` never raises for a source or item failure; it returns the run with
`status` set (`failed` / `partial` / `completed`) and the caller's normal commit
persists the memory. The only hard error is an unknown campaign. The failure test
was rewritten to assert the returned run and the persisted rows rather than an
exception.

**Pre-existing, not fixed here:** every existing creator pipeline has the same
latent flaw — `finish_run` raises `PipelineFailureError` when all units fail, the
callers in `run.py` and `api/jobs.py` commit only after a normal return, so a
fully failed run leaves no `ResearchRun` row (the Gemini-quota failure earlier in
this session shows exactly this `ROLLBACK`). Fixing it means touching every pipeline
caller — "creator collector redesign", out of scope. Flagged for a dedicated slice.

### 3. The live approved source is YouTube search, via a small adapter enablement

With Reddit blocked, the remaining approved, free, non-evasive, already-wired source
is YouTube through yt-dlp. yt-dlp natively accepts `ytsearchN:query` in the URL
position, but the adapter's `profile_url` rewrote every non-http identifier into a
channel URL, and a search listing would have emitted a bogus "profile" evidence row
(yt-dlp titles the search playlist with the query string). Two additive changes to
`ytdlp.py`: `is_search()` + pass-through in `profile_url`, and skip the profile
item for a search. No interface change; the channel path is unchanged and a
regression test pins it. Four unit tests cover the search path.

This is a judgment call worth the gate's attention: it is "reuse existing
adapter" in spirit, but it does add a capability to that adapter. If the
preference is Reddit-via-OAuth as the canonical discovery source, this can stay as
the second source or be reverted.

## Lesson reused

`executed_at` on the ledger is client-side (Slice 6's lesson). The two live runs
show it doing its job: 23:15:45 and 23:16:58, not one transaction timestamp.

## Assumptions

- "One approved source" is not named in the doc. Reddit was the first choice
  (a subreddit is a community signal, no key needed); YouTube search is the source
  that actually works today.
- The CLI commands are the minimal way to make "campaign starts discovery run"
  observable by a person, consistent with how every other pipeline in this repo is
  driven (`corp/workers/run.py`). No HTTP API surface, per the gate assessment.
- `archive_reference` is stored relative to `CORP_DATA_PATH` so the SD → SSD move in
  §24 is a config change, not a data migration.
- Captions: `fetch_youtube_caption` returned nothing for the three live videos, so
  only `video` evidence was stored. Not investigated here; the collector stores
  whatever the adapter yields.

## Open items / risks

- Reddit adapter: needs OAuth credentials to work live; currently `VERIFY`-tagged
  and blocked unauthenticated.
- Failed runs in the pre-existing creator pipelines are rolled back rather than
  recorded (see problem 2). Dedicated slice recommended.
- The gated pytest live test (`test_live_youtube_search_discovery`, needs
  `CORP_LIVE_TESTS=1`) exists but the acceptance evidence above comes from the CLI
  runs, which exercise more of the path.
- Unchanged from earlier slices: `tests/integration/test_migration.py` and
  `tests/api/test_endpoints.py` remain broken due to another machine's hardcoded
  assumptions.
