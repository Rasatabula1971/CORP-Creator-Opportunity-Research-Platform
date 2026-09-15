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
            creators = await self._eligible_creators(campaign_id)
            if self._cfg.limit is not None:
                creators = creators[: self._cfg.limit]

            results: list[dict] = []
            succeeded = incomplete = skipped = errored = 0

            for creator in creators:
                if not self._cfg.force and creator.status != DEFAULT_ELIGIBLE_STATUS:
                    skipped += 1
                    results.append({
                        "creator_id": creator.id,
                        "name": creator.name,
                        "outcome": "skipped",
                        "reason": (
                            f"status={creator.status.value}, "
                            f"not {DEFAULT_ELIGIBLE_STATUS.value}"
                        ),
                    })
                    stats.skip()
                    continue

                try:
                    report = await self._researcher.run(
                        creator.id, skip_collect=self._cfg.skip_collect,
                    )
                except Exception as exc:  # one bad creator must not sink the batch
                    errored += 1
                    results.append({
                        "creator_id": creator.id,
                        "name": creator.name,
                        "outcome": "errored",
                        "reason": str(exc)[:500],
                    })
                    stats.fail(exc)
                    logger.warning(
                        "research batch: creator %s errored: %s", creator.id, exc,
                    )
                    continue

                if report.final_status == CreatorStatus.HUMAN_REVIEW.value:
                    succeeded += 1
                    outcome = "succeeded"
                else:
                    incomplete += 1
                    outcome = "incomplete"
                results.append({
                    "creator_id": creator.id,
                    "name": creator.name,
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
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception(
                "Campaign research batch failed for campaign %s", campaign_id,
            )
            raise

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
