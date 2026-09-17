"""Campaign research batch (Slice 15).

The last mile of the niche pipeline: drive the existing per-creator
``ResearchOrchestrator`` (collect -> intelligence -> cluster -> intent ->
score -> dossier -> HUMAN_REVIEW, pre-dating the niche slices) across every
creator onboarded (Slice 14) under a campaign's SELECTED niches.

``CreatorResearcher`` is a narrow protocol — anything with an async
``run(creator_id, *, skip_collect=False) -> ResearchReport`` method, which
``ResearchOrchestrator`` already satisfies. Tests inject a fake so batch
selection/skip/dedup logic is verified without a real LLM provider or yt-dlp
collector.

One creator failing outright (an exception from the researcher) must not
sink the batch — the same resilience rule as every other multi-item pipeline
in this codebase (AcquisitionCollector, NicheDiscoveryCollector, ...).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    start_run,
)

logger = logging.getLogger(__name__)

PIPELINE = "campaign_research_batch"

# Only a creator that hasn't started research yet is eligible without --force.
DEFAULT_ELIGIBLE_STATUS = CreatorStatus.DISCOVERED


class ResearchReport(Protocol):
    final_status: str


class CreatorResearcher(Protocol):
    async def run(
        self, creator_id: str, *, skip_collect: bool = False,
    ) -> ResearchReport: ...


@dataclass(frozen=True, slots=True)
class BatchConfig:
    limit: int | None = None
    skip_collect: bool = False
    force: bool = False


class CampaignResearchBatch:
    def __init__(
        self,
        researcher: CreatorResearcher,
        session: AsyncSession,
        config: BatchConfig | None = None,
    ) -> None:
        self._researcher = researcher
        self._session = session
        self._cfg = config or BatchConfig()

    async def run_campaign(self, campaign_id: str) -> ResearchRun:
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "limit": self._cfg.limit,
                "skip_collect": self._cfg.skip_collect,
                "force": self._cfg.force,
            },
            prompt_versions={},
            model_versions={},
            scope=RunScope.CROSS,
            run_type=RunType.CAMPAIGN_RESEARCH_BATCH,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()

        try:
            rows = await self._eligible_creators(campaign_id)
            if self._cfg.limit is not None:
                rows = rows[: self._cfg.limit]
            # Plain values, not ORM instances. The orchestrator rolls the
            # shared session back when a stage crash poisoned it, and a
            # rollback expires every loaded Creator (expire_on_commit only
            # covers commit). An AsyncSession cannot lazy-load an expired
            # attribute, so the next creator's first touch would raise
            # MissingGreenlet and sink the batch.
            creators = [(c.id, c.name, c.status) for c in rows]

            results: list[dict] = []
            succeeded = incomplete = skipped = errored = 0

            for creator_id, name, status in creators:
                if not self._cfg.force and status != DEFAULT_ELIGIBLE_STATUS:
                    skipped += 1
                    results.append({
                        "creator_id": creator_id,
                        "name": name,
                        "outcome": "skipped",
                        "reason": (
                            f"status={status.value}, "
                            f"not {DEFAULT_ELIGIBLE_STATUS.value}"
                        ),
                    })
                    stats.skip()
                    continue

                try:
                    report = await self._researcher.run(
                        creator_id, skip_collect=self._cfg.skip_collect,
                    )
                except Exception as exc:  # one bad creator must not sink the batch
                    errored += 1
                    results.append({
                        "creator_id": creator_id,
                        "name": name,
                        "outcome": "errored",
                        "reason": str(exc)[:500],
                    })
                    stats.fail(exc)
                    logger.warning(
                        "research batch: creator %s errored: %s", creator_id, exc,
                    )
                    run = await self._reattach_run(run)
                    continue

                if report.final_status == CreatorStatus.HUMAN_REVIEW.value:
                    succeeded += 1
                    outcome = "succeeded"
                else:
                    incomplete += 1
                    outcome = "incomplete"
                results.append({
                    "creator_id": creator_id,
                    "name": name,
                    "outcome": outcome,
                    "reason": report.final_status,
                })
                stats.ok()

            stats.extra.update(
                creators_total=len(creators),
                succeeded=succeeded,
                incomplete=incomplete,
                skipped=skipped,
                errored=errored,
                results=results,
            )
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            try:
                if run.status == "running":
                    await fail_run(self._session, run, exc)
            except Exception:  # expired run or poisoned session: keep the original error
                logger.exception(
                    "could not mark batch run failed for campaign %s", campaign_id,
                )
            logger.exception(
                "Campaign research batch failed for campaign %s", campaign_id,
            )
            raise

    async def _reattach_run(self, run: ResearchRun) -> ResearchRun:
        """Make ``run`` safe to touch after a researcher crash.

        ``ResearchOrchestrator._persist_after_crash`` rolls the shared session
        back when the crash poisoned it. That expires ``run`` if its row was
        already committed by an earlier orchestrator step, and expunges it if
        the row was still pending; either way the batch's next read or flush
        of it would misbehave. Refresh or re-add so the batch can keep going
        and still close its own run.
        """
        if run in self._session:
            await self._session.refresh(run)
        else:
            self._session.add(run)
            await self._session.flush()
        return run

    async def _eligible_creators(self, campaign_id: str) -> list[Creator]:
        result = await self._session.execute(
            select(Creator)
            .join(CreatorNiche, CreatorNiche.creator_id == Creator.id)
            .join(CampaignNiche, CampaignNiche.niche_id == CreatorNiche.niche_id)
            .where(
                CampaignNiche.campaign_id == campaign_id,
                CampaignNiche.status == CampaignNicheStatus.SELECTED,
            )
            .distinct()
            .order_by(Creator.created_at)
        )
        return list(result.scalars().all())
