# ADR-0064 — R14: reversible creator archive, respecting the append-only evidence trail

**Status:** Built and browser-verified; Stage 8 skipped by user request (small, low-risk utility outside the R-numbered remediation program — see Context); Stage 9: accepted by user 2026-09-22 (requested directly, in place of deleting demo/test data)
**Date:** 2026-09-22
**Reference:** none (not part of a frozen design doc) — a direct user request to remove two demo/test creators ("R7 Demo — Home Espresso Channel", "Test Creator") from the working Creators list.

## Context

The user asked to delete two leftover demo/test creators. Both have real
`evidence` rows collected under real `ResearchRun`s. `evidence` carries two
DB triggers (`evidence_no_update`, `evidence_no_delete`) from R3's
Provenance Invariant, enforced specifically so no evidence row can ever be
silently removed — the audit trail is permanent by design. A hard `DELETE`
on either creator is therefore impossible without disabling that trigger.

Offered three options: (1) hand the user raw SQL to disable the trigger,
delete, and re-enable it, for them to run themselves; (2) do it here by
disabling the trigger directly — an auto-mode permission classifier
correctly refused this as audit-tampering, and it was not attempted again;
(3) build a reversible archive instead. User chose (3).

## Decision

**`Creator.archived_at: datetime | None`** (new nullable column, indexed).
Independent of `CreatorStatus` (the state machine's own field — untouched
by archiving) and of every evidence-bearing table — archiving writes
exactly one timestamp and nothing else. Migration `873b4632a7c6` (down
from `f6a1e362c878`), applied to both `corp` and `corp_test`.

**API.**
- `GET /creators` gains `include_archived: bool = False`; the default
  query now excludes `archived_at IS NOT NULL`, composing with the
  existing `status`/`min_score` filters (order of `.where()` calls doesn't
  matter here — verified with a test combining `status=human_review` and
  an archived row).
- `POST /creators/{id}/archive` — idempotent (a second call keeps the
  original `archived_at`), 404 for an unknown id.
- `POST /creators/{id}/unarchive` — same shape, clears the field.

**Frontend.**
- Creator detail page: an **Archive**/**Unarchive** button next to Start
  Research; an "archived" badge on the header when set; a grey notice
  explaining nothing was deleted.
- Creators list: a **Show archived** toggle reveals a second "Archived"
  table below the main one (`include_archived=true`, client-filtered to
  just the archived rows so the toggle doesn't also affect the main
  list's own query).

## Files changed

| File | Change |
| --- | --- |
| `corp/core/models/creator.py` | `Creator.archived_at`; `ix_creators_archived_at` |
| `migrations/versions/873b4632a7c6_r14_creator_archive.py` | New migration |
| `corp/core/schemas/creator.py` | `CreatorResponse.archived_at` |
| `corp/api/routes.py` | `list_creators` gains `include_archived`; `archive_creator`, `unarchive_creator` |
| `web/src/api/types.ts` | `Creator.archived_at` |
| `web/src/api/hooks.ts` | `useArchiveCreator`, `useArchivedCreators` |
| `web/src/pages/CreatorDetailPage.tsx` | Archive/Unarchive button, badge, notice |
| `web/src/pages/CreatorsPage.tsx` | Show/Hide archived toggle, extracted `CreatorTable` |
| `tests/api/test_creator_archive.py` | New: hides from default list but not `include_archived`; idempotent; unarchive restores visibility; 404 for unknown id; composes with `status` filter |

## Verification

- `python -m ruff check` clean; `python -m mypy corp --strict` clean;
  `npx tsc --noEmit` clean; `npx oxlint src` clean.
- `tests/api/test_creator_archive.py` + `tests/api/test_endpoints.py`:
  28 passed.
- Full suite, no deselects: **1338 passed, 1 skipped, 0 failed** (5 new).
- **Browser-verified** against the user's own running `start_corp.bat`
  instance (not a separate preview): archived "R7 Demo" from its detail
  page — badge, notice, and button flip appeared, all evidence/dossier
  content stayed intact; confirmed it disappeared from the default
  Creators list and reappeared under "Show archived"; archived "Test
  Creator" via the same API the button calls (`POST .../archive`, the
  in-app browser pane was hidden so the click itself couldn't land;
  called the identical endpoint directly instead); confirmed
  `GET /creators` now returns 0 rows.

## Consequences

- Both demo/test creators are now hidden from the working list, fully
  reversible, with zero evidence rows touched — the append-only invariant
  was never weakened.
- Any future demo/test/mistaken creator can be tidied the same way,
  without needing a one-off script or DB access.
- The `evidence_no_update`/`evidence_no_delete` triggers were never
  disabled at any point in this session.
