# Slice 18 — Creator Intelligence Dashboard

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

The `CreatorDetailPage` was a minimal stub showing only the creator's name,
status, platform accounts, and a "Start Research" button. All the
intelligence data (clusters, scores, signals, dossier, decisions) was
available via API endpoints and React Query hooks added in earlier slices
but had no UI surface. This slice builds the **Gate A review console** —
the page a human operator uses to evaluate a creator's research output and
record an approve/reject/watch decision.

### New sections on CreatorDetailPage

1. **Data Coverage + Score Band** — four stat tiles (score band, source
   count, evidence count, cluster count) from the dossier endpoint, giving
   an at-a-glance view of research depth.

2. **Gate A Decision Panel** — expandable form with Approve / Watch /
   Reject buttons and optional rationale text. Uses `useRecordDecision`
   hook (existing). Hidden when creator is already approved or rejected.

3. **Opportunities (Clusters)** — expandable cards for each problem cluster,
   sorted by aggregate score descending. Each card shows:
   - Label and description
   - Aggregate score badge
   - Commercial signal level badge
   - Member count
   - Expanded: frequency, recency, evidence strength, confidence band,
     component score breakdown, signal rationale
   - Observations preview (top 5 from `useClusterObservations`)

4. **Decision History** — chronological list of past Gate A decisions with
   status badge, gate, rationale, and timestamp.

5. **Score Weights** — the scoring model's weight configuration from the
   dossier, displayed as a grid.

### Status badge colors

Added badge colors for:
- Decision actions: `approve`, `reject`, `watch`
- Signal levels: `strong`, `moderate`, `weak`, `none`

## Implementation

No new API endpoints, models, or hooks — every data source was already
built in previous slices. This slice wires 6 existing hooks into the page:

- `useClusters(id)` — Slice 8 backend, existing hook
- `useClusterObservations(clusterId)` — Slice 8, existing hook
- `useDossier(id)` — Slice 8/Step 8, existing hook
- `useDecisions(id)` — Slice 8/Step 8, existing hook
- `useRecordDecision(id)` — Slice 8/Step 8, existing hook
- `useJob(id)` — already in use

## Acceptance criteria and how each is met

- **Research output is visible in the browser, not just the CLI.**
  Clusters, scores, signals, component breakdowns, and observations all
  render on the CreatorDetailPage.
- **A human can approve/reject/watch from the UI.**
  DecisionPanel component with three action buttons + rationale field.
- **Decision history is visible.**
  DecisionHistory section with chronological list.
- **Data coverage is surfaced so the operator can judge research depth.**
  Four stat tiles from the dossier endpoint.

## Verification

- TypeScript type check clean (`tsc --noEmit`).
- No new backend code — all endpoints tested in previous slices.

## Assumptions

- The decision panel records against `gate_a` by default (matching the
  existing hook behavior from Step 8).
- Observations preview shows only the top 5 per cluster — a future slice
  could add pagination or a dedicated observations page.
- Component scores and weights use `replace(/_/g, " ")` for display — a
  future slice could add human-readable labels.
