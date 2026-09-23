# ADR-0063 — R12d: the re-scan outcome is visible in the dossier panel and on the Re-scan page

**Status:** Stage 8: round 1 REVISE (one blocking — a resurfaced dossier the reviewer parks again was labelled "unchanged" — fixed with a test; hardening and doc items applied), round 2 ACCEPT (comment wording aligned; a legacy row with null `completed_at` but later `started_at` would sort behind a fully-timestamped one — unreachable via `fail_run`, noted); Stage 9: accepted by user 2026-09-22
**Date:** 2026-09-22
**Reference:** `docs/design/R12_watch_rescan_recollect.md` (frozen) §3.5
"Human-visible behaviour"; task R12d. Closes R12.

## Context

R12a writes `content["rescan"]` on every dossier version the
`WatchRescanner` produces, and R12c makes the scheduler produce them. The
UI showed none of it: a resurfaced dossier appeared in the review queue
with no explanation, a still-parked one gave no sign it had been
re-scanned, and the `/rescan` page could not tell "never looked at" from
"re-scanned and unchanged" from "re-scan failed".

## Decision

**API.** `GET /dossiers/watching` rows gain `last_rescan`
(`LastRescanResponse | null`): `outcome` `unchanged` or `resurfaced` (from
the dossier's own `rescan` block — it *is* the version the re-research
produced; a resurfaced or Research More version is WATCHING again as soon
as the reviewer parks it via the dossier gate, so all three §3.5 outcomes
can appear) or `failed` (from the newest failed `watch_rescan` run whose
`config_snapshot.dossier_id` targets this dossier — the old dossier stays
active on failure, ADR-0061), whichever is newer; with `trigger`
(`watch` / `research_more` — "last re-scan" means the last re-research of
either trigger, and the page says "via Research More" when it was the
reviewer's), `at`, `reason`, `score_delta`, `new_evidence_count`, `error`,
`run_id`. One extra `DISTINCT ON (dossier_id)` query per page for the
listed ids (newest by `completed_at`, then `started_at`, nulls last);
block times are normalised to UTC; a malformed `rescan` block is ignored
rather than 500-ing the page.

**Re-scan page (`/rescan`).** New "Last Re-scan" column: `never`, or an
`unchanged`/`resurfaced`/`failed` badge with the date, "via Research
More" where applicable, and the reason/error (truncated, full text on
hover).

**Dossier panel (creator page).** A line under the niche path, per §3.5:
- `Resurfaced from Watch on <date> — <reason>` (green) when the re-scan
  strengthened the evidence;
- `Updated by Research More on <date> — score ±x / n new evidence rows`
  (blue) for a Research More result;
- `Re-scanned <date>, unchanged — score ±x / n new evidence rows` (grey)
  for one still parked.

§3.5 places the resurfaced line "in the recommendation block"; it is
rendered as its own line directly above the recommendation card, where it
reads as the version's provenance rather than part of the recommendation.
`score_delta` can be `null` (no prior score); the line then shows `n/a`.

Nothing changes at the decision gates.

**Stage 8 revise round (applied).**
- *Blocking.* The first cut assumed a resurfaced dossier could never be
  WATCHING and labelled every block `unchanged`. The dossier gate's Watch
  sets `WATCHING` on the same row, content untouched, so a resurfaced (or
  Research More) version the reviewer re-parks would have shown an
  `unchanged` badge beside a "score +0.08" reason. `outcome` now follows
  `block["resurfaced"]`; `trigger` added; test
  `test_resurfaced_then_rewatched_reports_resurfaced`.
- Failed-run lookup: `DISTINCT ON` (one row per dossier instead of every
  retry), ordered by `completed_at` then `started_at` nulls last so the
  ordering agrees with the reported `at`; naive block timestamps
  normalised to UTC before comparison
  (`test_failed_run_with_null_started_at_and_naive_block_time`).
- Frontend `DossierRescanBlock.score_delta` is `number | null` like the
  worker writes it; `RescanLine` guards it.
- Recorded: recommendation-block placement (above); the seeded demo
  block's reason wording ("band medium -> high") is hand-written — the
  worker's is "confidence medium → high"; the rendering is the same.

## Files changed

| File | Change |
| --- | --- |
| `corp/core/schemas/dossier.py` | `LastRescanResponse`; `WatchingDossierResponse.last_rescan` |
| `corp/api/routes.py` | `list_watching_dossiers` selects `content`, `_latest_failed_rescans`, `_last_rescan` |
| `web/src/api/types.ts` | `LastRescan`, `DossierRescanBlock`, `WatchingDossier.last_rescan`, `PersistedDossier.content.rescan` |
| `web/src/pages/RescanPage.tsx` | `LastRescanCell` + column |
| `web/src/pages/CreatorDetailPage.tsx` | `RescanLine` in `PersistedDossierPanel` |
| `web/src/components/ui.tsx` | badge colours `unchanged`, `resurfaced` |
| `tests/api/test_watching_dossiers.py` | New (7): never re-scanned → null; unchanged from the block; failed from the newest run (another dossier's run ignored); newer outcome wins both ways; resurfaced-then-rewatched and Research More report their outcome/trigger; null `started_at` legacy row and naive block time; malformed block ignored |

No migration.

## Verification

- `python -m ruff check` clean; `python -m mypy corp --strict` clean;
  `npx tsc --noEmit` clean; `npx oxlint src` clean.
- `tests/api/test_watching_dossiers.py`: 7 passed after round 1 (5 before).
- Full suite, no deselects, after round 1: **1333 passed, 1 skipped,
  0 failed**. The round-1 run reported 1 failure out of 1331 whose name
  was not captured; a targeted rerun of `tests/api` + the rescan
  integration files (146) and the full rerun were both clean, so it is
  recorded here as an unidentified one-off, not as resolved.
- **Browser-verified** against the dev stack (`corp-backend` 8010 /
  `corp-frontend` 5173) with seeded data: `/rescan` shows the watched
  "R12d Demo — Watched Channel" row with a `failed` badge, today's date and
  the error text; its creator page shows "Re-scanned 19/09/2026, unchanged
  — score +0.01 / 2 new evidence rows"; the R7 demo creator's page shows
  "Resurfaced from Watch on <date> — score +0.08; band medium -> high; 14
  new evidence rows".
- Incidental live verification of **R12c**: on backend start the real
  scheduler ticked, found the seeded due dossier, ran the real re-research
  path, failed at `creator_research` ("has no platform accounts"),
  recorded the failed `watch_rescan` run, left the dossier WATCHING and
  moved `next_recheck_at` to tomorrow (`retry_days`) — exactly ADR-0062's
  contract, and it is that real failed run the page displays.

## Consequences

- R12 is complete: Watch re-scans re-collect, resurface only on stronger
  evidence, Research More completes, and every outcome is visible.
- Follow-up (not in scope): the weak-niche "revisit later" state (design
  §3.6, "R13"), and a "re-scan in progress" indicator if a tick's
  duration ever becomes noticeable.
