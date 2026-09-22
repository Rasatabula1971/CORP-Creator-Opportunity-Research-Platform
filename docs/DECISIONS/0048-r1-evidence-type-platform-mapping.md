# ADR-0048 — R1: Evidence-type fallback mapping keyed on real adapter platform strings

**Status:** Accepted (Stage 8: ACCEPT, one non-blocking wording fix applied; Stage 9: accepted by user 2026-09-21)
**Date:** 2026-09-21
**Reference:** `docs/REMEDIATION_PLAN_2026-09.md` R1; audit finding #1

## Context

Commit b137205 introduced `infer_evidence_type()` so the three legacy
`collect()` write paths (`collector.py`, `discovery.py`, `multi_discovery.py`)
set `Evidence.evidence_type` and satisfy the Provenance Invariant. Its lookup
table was keyed on display-style names (`google_trends`, `app_store`,
`search_demand`, `patreon`, `substack`) rather than the strings the adapters
actually put in `NormalizedContent.source_platform` (`googletrends`,
`appstore`, `searchdemand`, `patreon_substack`), and `web` / `tiktok` were not
mapped at all. Rows from those platforms therefore still landed with
`evidence_type = NULL` — the fix was only partially effective. No test tied the
table to the adapters.

## Decision

- Re-key `_PLATFORM_EVIDENCE_TYPE` on the exact strings in
  `corp.workers.adapters.registry.KNOWN_PLATFORMS`. Capability per platform is
  taken from the spec's adapter→capability table (p. 20); where the table lists
  several capabilities, the first-listed one **that the adapter actually
  implements** is used for the legacy paths (the T3 fan-out sets the precise
  type per interface call). Example: the spec lists Amazon as Transaction,
  Solution, Dissatisfaction, but `AmazonReviewAdapter` implements only
  `DissatisfactionProvider`, so `amazon_reviews → DISSATISFACTION`.
- `tiktok → PROBLEM` (creator content/comments, same as YouTube).
- `web → MONETISATION`. The spec table does not list Web Presence and
  `WebPresenceAdapter` implements no capability interface; it detects a
  creator's own website/store, which `scoring_pipeline.py` already consumes as
  a commerce signal. Disclosed judgement call — revisit if the user prefers it
  untyped.
- Lookup is case-insensitive.
- Removed keys that no adapter emits (`gumroad`, `etsy`, `udemy`, `amazon`,
  `google_trends_rss`); kept spec-planned platforms (`pinterest`, `quora`,
  `kickstarter`, `indiegogo`, `trustpilot`, `product_hunt`, `google_books`,
  `google_shopping`) so future adapters get a default.

## Files changed

| File | Change |
| --- | --- |
| `corp/core/models/evidence.py` | Re-keyed mapping; case-insensitive lookup; comment explaining primary-capability rule |
| `tests/core/test_evidence_type_mapping.py` | New: every `KNOWN_PLATFORMS` entry maps; each adapter's mapped type ∈ its declared capability interfaces; case-insensitivity; unknown → `None` |

## Verification

- `mypy --strict` clean on both changed files.
- `ruff check` on `evidence.py`: only the four pre-existing repo-wide UP042
  (`str, Enum` → `StrEnum`) hits, none introduced here; clean on the test file.
- `tests/core/test_evidence_type_mapping.py` + `tests/workers/test_multi_discovery.py`
  + `tests/integration/test_discovery.py` + `tests/integration/test_collector.py`
  (one known pre-existing failure deselected): 56 passed, 1 skipped.

## Consequences

- All fourteen registered platforms now yield a non-NULL `evidence_type` on the
  legacy paths. Existing NULL rows are addressed by R3 (backfill + `NOT NULL`).
- A renamed or newly registered platform string fails the new test until the
  mapping is updated.

## Note on unrelated working-tree state

`CORP1_Product_Spec_Build_Plan.pdf` is untracked at the repo root (the spec
reference copy); not part of this change.
