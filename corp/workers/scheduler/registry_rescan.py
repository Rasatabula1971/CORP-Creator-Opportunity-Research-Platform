"""Registry Re-scan Scheduler (CORP1 Stage 5, T10).

Architecture invariant (Stage 4): "Watched dossiers are automatically
re-scored within 24 hours of their niche's next_recheck_at passing, with
no manual action." A dossier reaches ``DossierStatus.WATCHING`` via T8's
Watch decision -- "parked... so it can resurface on its own if the
evidence strengthens" (Stage 3). Re-scoring means regenerating the
persisted dossier via T6's ``DossierGenerator.generate_and_persist``,
which reads whatever is currently the latest ``OpportunityScore`` for
that creator/niche and produces a fresh ``Dossier`` row (superseding the
watched one, T6's existing latest-wins convention) defaulting back to
``PENDING_REVIEW`` -- exactly "resurfacing" it into the human review
queue if the underlying score changed. This module does not collect new
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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.niche import Niche
from corp.workers.dossier.generator import DossierGenerator
from corp.workers.intelligence.niche_discovery import DiscoveryConfig

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


async def find_due_watched_dossiers(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Dossier]:
    """Every currently-active (never-superseded) WATCHING dossier whose
    niche's next_recheck_at has passed. ``now`` is injectable so tests can
    time-travel without monkeypatching a stdlib global."""
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
    )
    return list(result.scalars().all())


async def rescan_watched_dossiers(
    session: AsyncSession,
    scoring_rules_path: str,
    *,
    now: datetime | None = None,
    recheck_days: int = 90,
) -> RescanStats:
    """One re-scan pass. Regenerates the dossier for every due WATCHING
    dossier and advances its niche's next_recheck_at so this same
    dossier isn't picked up again on the very next tick. A single
    dossier's failure is logged and skipped, never aborts the batch --
    matching every other pipeline in this codebase (PipelineStats'
    fail-and-continue convention).

    Does not commit -- the caller controls the transaction boundary,
    same as every other pure worker function in this codebase
    (corp.workers.handoff.corp2_export.build_handoff_package, T9).
    """
    now = now or datetime.now(UTC)
    due = await find_due_watched_dossiers(session, now=now)
    generator = DossierGenerator(session, rules_path=scoring_rules_path)

    # Advance next_recheck_at optimistically so a concurrent tick does not
    # pick up the same dossiers while this one is still processing.
    for dossier in due:
        niche = await session.get(Niche, dossier.niche_id)
        if niche is not None:
            niche.next_recheck_at = now + timedelta(days=recheck_days)
    await session.flush()

    rescored = 0
    failed = 0
    for dossier in due:
        try:
            await generator.generate_and_persist(dossier.creator_id, dossier.niche_id)
            niche = await session.get(Niche, dossier.niche_id)
            if niche is not None:
                niche.last_researched_at = now
        except Exception as exc:  # noqa: BLE001 -- one bad dossier must not block the rest
            logger.warning("Registry re-scan failed for dossier %s: %s", dossier.id, exc)
            failed += 1
        else:
            rescored += 1

    await session.flush()
    return RescanStats(checked=len(due), rescored=rescored, failed=failed)


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
    ) -> None:
        self._session_factory = session_factory
        self._scoring_rules_path = scoring_rules_path
        # recheck_days comes from the same rules file T3's discovery
        # engine already reads it from -- one source of truth for the
        # registry's re-scan cadence, not a second hardcoded constant.
        self._recheck_days = DiscoveryConfig.from_rules(niche_rules_path).recheck_days
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
                stats = await rescan_watched_dossiers(
                    session, self._scoring_rules_path, recheck_days=self._recheck_days
                )
                await session.commit()
                if stats.checked:
                    logger.info(
                        "Registry re-scan: checked=%d rescored=%d failed=%d",
                        stats.checked,
                        stats.rescored,
                        stats.failed,
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
