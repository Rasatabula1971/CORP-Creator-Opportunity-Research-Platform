"""Registry Re-scan Scheduler (CORP1 Stage 5, T10).

Architecture invariant (Stage 4): "Watched dossiers are automatically
re-scored within 24 hours of their niche's next_recheck_at passing, with
no manual action." A dossier reaches ``DossierStatus.WATCHING`` via T8's
Watch decision -- "parked... so it can resurface on its own if the
evidence strengthens" (Stage 3). Re-scoring means regenerating the
persisted dossier via T6's ``DossierGenerator.generate_and_persist``,
which reads whatever is currently the latest ``OpportunityScore`` for
that creator/niche and produces a fresh ``Dossier`` row (superseding the
watched one, T6's existing latest-wins convention). It resurfaces to
``PENDING_REVIEW`` only when the regenerated content actually differs
from the watched dossier's; identical content stays ``WATCHING`` (R8,
ADR-0054). This module does not collect new
evidence itself; that already happens on whatever cadence drives
``OpportunityScore``/``ResearchRun`` updates elsewhere. Its own job is
narrower: notice a watched niche is due, regenerate its dossier from
current data, and push the niche's own recheck clock forward so the same
dossier isn't reprocessed on the very next tick.

Runs as an in-process scheduled job -- an ``asyncio`` loop, no new queue
infrastructure (Celery, RQ, cron) and no new dependency. Starting it is
left to whichever later task wires application startup (this task's
frozen scope is this one new file only, matching T7/T9's precedent of
shipping the tested logic before something else wires it in).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from corp.core.models.campaign_niche import CampaignNiche
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.niche import Niche
from corp.workers.dossier.generator import DossierGenerator
from corp.workers.intelligence.niche_discovery import DiscoveryConfig
from corp.workers.watch_rescan import WatchRescanConfig, WatchRescanner, content_fingerprint

__all__ = [
    "RescanDeferredError",
    "RescannerHandle",
    "content_fingerprint",
    "find_due_watched_dossiers",
    "rescan_watched_dossiers",
]


@dataclass(slots=True)
class RescannerHandle:
    """A rescanner plus the cleanup for whatever it was built around (the
    LLM provider's HTTP client). The scheduler closes it after each tick."""

    rescanner: WatchRescanner
    aclose: Callable[[], Awaitable[None]]


# Called once per tick with the tick's session and the watch_rescan config.
# Returns a handle (re-research), None (re-render only: no LLM provider
# configured) or raises RescanDeferredError (skip the tick untouched).
RescannerFactory = Callable[
    [AsyncSession, WatchRescanConfig], Awaitable["RescannerHandle | None"]
]

logger = logging.getLogger(__name__)

# Hourly comfortably satisfies the 24-hour SLA with margin for a missed
# or slow tick, without polling so often it's meaningfully different
# from an event-driven trigger.
DEFAULT_INTERVAL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class RescanStats:
    checked: int = 0
    rescored: int = 0
    failed: int = 0
    # Regenerated but content-identical to the watched dossier: kept
    # WATCHING rather than resurfaced (counted inside ``rescored``).
    unchanged: int = 0
    # R12c: re-researched and put back in the review queue (inside rescored).
    resurfaced: int = 0
    # R12c: due but not processed this tick (over the per-tick cap, or the
    # dossier's campaign has a job running); still due next tick.
    deferred: int = 0


class RescanDeferredError(Exception):
    """Raised by a rescanner factory to defer the whole tick without touching
    any dossier -- e.g. every LLM provider is in cooldown (design §3.4)."""


class BusyCheck(Protocol):
    """True when a job is already queued/running for this dossier's campaign
    (``None`` when the niche has no campaign association) or its creator."""

    def __call__(self, campaign_id: str | None, creator_id: str) -> bool: ...


# content_fingerprint moved to corp.workers.watch_rescan (R12a) so the
# rescanner and this scheduler share one definition without an import cycle.


async def find_due_watched_dossiers(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Dossier]:
    """Every currently-active (never-superseded) WATCHING dossier whose
    niche's next_recheck_at has passed, longest-overdue first. ``now`` is
    injectable so tests can time-travel without monkeypatching a stdlib
    global."""
    now = now or datetime.now(UTC)
    result = await session.execute(
        select(Dossier)
        .join(Niche, Niche.id == Dossier.niche_id)
        .where(
            Dossier.status == DossierStatus.WATCHING,
            Dossier.superseded_at.is_(None),
            Niche.next_recheck_at.isnot(None),
            Niche.next_recheck_at <= now,
        )
        .order_by(Niche.next_recheck_at.asc(), Dossier.generated_at.asc())
    )
    return list(result.scalars().all())


async def _campaign_for_niche(session: AsyncSession, niche_id: str) -> str | None:
    return (
        await session.execute(
            select(CampaignNiche.campaign_id)
            .where(CampaignNiche.niche_id == niche_id)
            .order_by(CampaignNiche.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def rescan_watched_dossiers(
    session: AsyncSession,
    scoring_rules_path: str,
    *,
    now: datetime | None = None,
    recheck_days: int = 90,
    retry_days: int = 1,
    rescanner: WatchRescanner | None = None,
    max_dossiers: int | None = None,
    is_busy: BusyCheck | None = None,
) -> RescanStats:
    """One re-scan pass. Regenerates the dossier for every due WATCHING
    dossier. A single dossier's failure is logged and skipped, never
    aborts the batch -- matching every other pipeline in this codebase
    (PipelineStats' fail-and-continue convention).

    Per dossier (R8):
    * The regeneration runs inside a SAVEPOINT, so a database error for
      one dossier rolls back only that dossier and leaves the session
      usable for the rest of the batch.
    * The niche's recheck clock (``last_researched_at`` /
      ``next_recheck_at``) advances only on success. On failure
      ``next_recheck_at`` moves forward by ``retry_days`` -- soon enough
      that a transient error is retried, far enough that a persistent one
      does not log every tick -- instead of being silently deferred a
      whole ``recheck_days``.
    * If the regenerated content is identical to the watched dossier's
      (``content_fingerprint``), the new row stays WATCHING: nothing new
      for the human to see. Only changed content resurfaces to
      PENDING_REVIEW (T10's open product question, resolved here).

    R12c -- with a ``rescanner`` the dossier is RE-RESEARCHED rather than
    re-rendered: ``WatchRescanner.rescan(dossier_id, trigger="watch")``
    re-queries the niche, re-runs the creator chain, regenerates ideas and
    the dossier, and applies the "evidence strengthened" rule (design §3.3);
    the resurfaced/unchanged outcome comes from it. Because the creator
    chain commits between stages, this path cannot run inside a SAVEPOINT
    (a commit would end it); the rescanner's own failure handling keeps the
    old dossier intact instead, and the scheduler commits after each
    dossier. ``max_dossiers`` caps the work per tick (design §3.4); a
    dossier whose campaign or creator ``is_busy`` (a job already queued or
    running) is skipped and stays due. Both limits apply only with a
    ``rescanner`` -- they bound LLM/adapter cost, and the cheap re-render
    must keep T10's 24-hour SLA through any backlog. Without a ``rescanner``
    the pre-R12c re-render path runs unchanged -- the fallback when no LLM
    provider is configured.

    The rescanner shares this session and may roll it back mid-chain (the
    orchestrator does on a DB error), which expires every loaded object --
    so the loop works from plain ids captured up front, never from the
    ``Dossier`` rows after handing them over, and the failure branch first
    commits (keeping the rescanner's own failed-run bookkeeping) or, if the
    session is unusable, rolls back, before recording the retry clock in a
    fresh transaction.

    Without a rescanner, does not commit -- the caller controls the
    transaction boundary, same as every other pure worker function in this
    codebase (corp.workers.handoff.corp2_export.build_handoff_package, T9).
    """
    now = now or datetime.now(UTC)
    due = await find_due_watched_dossiers(session, now=now)
    generator = DossierGenerator(session, rules_path=scoring_rules_path)

    # Plain ids: the rescanner may expire these rows (see docstring).
    targets = [(d, d.id, d.niche_id, d.creator_id) for d in due]

    rescored = failed = unchanged = resurfaced = deferred = 0
    processed = 0
    for dossier, dossier_id, niche_id, creator_id in targets:
        if rescanner is not None and max_dossiers is not None and processed >= max_dossiers:
            deferred += 1
            continue
        if rescanner is not None and is_busy is not None:
            campaign_id = await _campaign_for_niche(session, niche_id)
            if is_busy(campaign_id, creator_id):
                logger.info(
                    "Registry re-scan: dossier %s deferred, a job is running for "
                    "campaign %s / creator %s",
                    dossier_id, campaign_id, creator_id,
                )
                deferred += 1
                continue
        processed += 1

        is_unchanged = False
        try:
            if rescanner is not None:
                outcome = await rescanner.rescan(dossier_id, trigger="watch")
                is_unchanged = not outcome.decision.resurfaced
                niche = await session.get(Niche, niche_id)
                if niche is not None:
                    niche.last_researched_at = now
                    niche.next_recheck_at = now + timedelta(days=recheck_days)
                await session.commit()
            else:
                previous = content_fingerprint(dossier.content)
                async with session.begin_nested():
                    regenerated = await generator.generate_and_persist(
                        dossier.creator_id, dossier.niche_id
                    )
                    is_unchanged = content_fingerprint(regenerated.content) == previous
                    if is_unchanged:
                        regenerated.status = DossierStatus.WATCHING
                    niche = await session.get(Niche, niche_id)
                    if niche is not None:
                        niche.last_researched_at = now
                        niche.next_recheck_at = now + timedelta(days=recheck_days)
        except Exception as exc:  # noqa: BLE001 -- one bad dossier must not block the rest
            logger.warning("Registry re-scan failed for dossier %s: %s", dossier_id, exc)
            failed += 1
            if rescanner is not None:
                # Keep the rescanner's failed-run / restore bookkeeping if the
                # session can still commit; otherwise clear it for the batch.
                try:
                    await session.commit()
                except Exception:  # noqa: BLE001
                    await session.rollback()
            try:
                niche = await session.get(Niche, niche_id)
                if niche is not None:
                    niche.next_recheck_at = now + timedelta(days=retry_days)
                if rescanner is not None:
                    await session.commit()
            except Exception:  # noqa: BLE001 -- session unusable; the tick reports the failure
                logger.exception("Could not record the retry for dossier %s", dossier_id)
                await session.rollback()
        else:
            # Counted only once the savepoint has released cleanly, so a
            # failure at release can't count a dossier as both unchanged
            # and failed.
            rescored += 1
            if is_unchanged:
                unchanged += 1
            else:
                resurfaced += 1

    await session.flush()
    return RescanStats(
        checked=len(due),
        rescored=rescored,
        failed=failed,
        unchanged=unchanged,
        resurfaced=resurfaced,
        deferred=deferred,
    )


class RegistryRescanScheduler:
    """The in-process scheduled job itself: an asyncio loop ticking every
    ``interval_seconds`` (default hourly), each tick opening its own
    session and running one rescan_watched_dossiers() pass, then
    committing. Call start() once (e.g. from application startup, when
    something wires that in) and stop() on shutdown."""

    MAX_CONSECUTIVE_FAILURES = 5

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        scoring_rules_path: str,
        niche_rules_path: str = "rules/niche_discovery_prompt.yaml",
        *,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        rescanner_factory: RescannerFactory | None = None,
        is_busy: BusyCheck | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._scoring_rules_path = scoring_rules_path
        # recheck_days comes from the same rules file T3's discovery
        # engine already reads it from -- one source of truth for the
        # registry's re-scan cadence, not a second hardcoded constant.
        self._recheck_days = DiscoveryConfig.from_rules(niche_rules_path).recheck_days
        # R12c: the re-research limits live in the same file (watch_rescan:).
        self._rescan_cfg = WatchRescanConfig.from_rules(niche_rules_path)
        # Per tick: returns a handle around a WatchRescanner (re-research),
        # None to fall back to re-render only (no LLM provider configured),
        # or raises RescanDeferredError to skip the tick (providers cooling).
        self._rescanner_factory = rescanner_factory
        self._is_busy = is_busy
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._consecutive_failures = 0

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_forever(self) -> None:
        while self._consecutive_failures < self.MAX_CONSECUTIVE_FAILURES:
            await self._tick()
            delay = self._interval_seconds
            if self._consecutive_failures > 0:
                delay = min(
                    self._interval_seconds * (2 ** self._consecutive_failures),
                    self._interval_seconds * 32,
                )
            await asyncio.sleep(delay)

    async def _tick(self) -> None:
        try:
            async with self._session_factory() as session:
                handle: RescannerHandle | None = None
                if self._rescanner_factory is not None and self._rescan_cfg.recollect_creator:
                    try:
                        handle = await self._rescanner_factory(session, self._rescan_cfg)
                    except RescanDeferredError as why:
                        logger.info("Registry re-scan tick deferred: %s", why)
                        self._consecutive_failures = 0
                        return
                try:
                    stats = await rescan_watched_dossiers(
                        session,
                        self._scoring_rules_path,
                        recheck_days=self._recheck_days,
                        rescanner=handle.rescanner if handle else None,
                        max_dossiers=self._rescan_cfg.max_dossiers_per_tick,
                        is_busy=self._is_busy,
                    )
                    await session.commit()
                finally:
                    if handle is not None:
                        try:
                            await handle.aclose()
                        except Exception:  # noqa: BLE001 -- the pass is already durable
                            logger.exception("Registry re-scan: closing the rescanner failed")
                if stats.checked:
                    logger.info(
                        "Registry re-scan: checked=%d rescored=%d resurfaced=%d "
                        "unchanged=%d deferred=%d failed=%d mode=%s",
                        stats.checked,
                        stats.rescored,
                        stats.resurfaced,
                        stats.unchanged,
                        stats.deferred,
                        stats.failed,
                        "re-research" if handle else "re-render",
                    )
            self._consecutive_failures = 0
        except Exception:  # noqa: BLE001 -- a failed tick must not kill the loop
            self._consecutive_failures += 1
            logger.exception(
                "Registry re-scan tick failed (consecutive=%d/%d)",
                self._consecutive_failures,
                self.MAX_CONSECUTIVE_FAILURES,
            )
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "Registry re-scan halted after %d consecutive failures",
                    self._consecutive_failures,
                )
