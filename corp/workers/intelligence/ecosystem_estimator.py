"""Creator ecosystem size estimator (Slice 11).

For each VERIFIED niche in a campaign, run a yt-dlp search to discover how
many unique creator channels are active in the niche. Populates
``creator_count_observed`` and ``target_band_creator_count`` on the
CampaignNiche row.

No API key, no LLM, no cost — only yt-dlp metadata search (free).

``target_band_creator_count`` is the subset of observed creators whose
subscriber count falls within a configurable band (default 10K–200K),
the sweet spot for partnership outreach.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.niche import Niche
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    start_run,
)

logger = logging.getLogger(__name__)

PIPELINE = "ecosystem_estimator"


class SearchAdapter(Protocol):
    """Minimal interface: run a yt-dlp search and return items."""

    async def collect(self, identifier: str) -> list: ...


@dataclass(frozen=True, slots=True)
class EcoConfig:
    search_count: int = 20
    min_followers: int = 10_000
    max_followers: int = 200_000


@dataclass(slots=True)
class NicheEcoResult:
    niche_id: str
    niche_name: str
    total_creators: int = 0
    target_band_creators: int = 0
    channels: list[dict] = field(default_factory=list)


class EcosystemEstimator:
    def __init__(
        self,
        adapter: SearchAdapter,
        session: AsyncSession,
        config: EcoConfig | None = None,
    ) -> None:
        self._adapter = adapter
        self._session = session
        self._cfg = config or EcoConfig()

    async def estimate(self, campaign_id: str) -> ResearchRun:
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "search_count": self._cfg.search_count,
                "min_followers": self._cfg.min_followers,
                "max_followers": self._cfg.max_followers,
            },
            prompt_versions={},
            model_versions={},
            scope=RunScope.NICHE,
            run_type=RunType.CREATOR_DISCOVERY,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()

        try:
            niches = await self._verified_niches(campaign_id)
            results: list[dict] = []

            for cn, niche in niches:
                result = await self._estimate_niche(niche)
                cn.creator_count_observed = result.total_creators
                cn.target_band_creator_count = result.target_band_creators
                await self._session.flush()
                stats.ok()

                results.append({
                    "niche": niche.canonical_name,
                    "total_creators": result.total_creators,
                    "target_band_creators": result.target_band_creators,
                    "channels": result.channels,
                })
                logger.info(
                    "Niche %r: %d creators observed, %d in target band",
                    niche.canonical_name,
                    result.total_creators,
                    result.target_band_creators,
                )

            stats.extra.update(
                niches_checked=len(niches),
                results=results,
            )
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception(
                "Ecosystem estimation failed for campaign %s", campaign_id
            )
            raise

    async def _estimate_niche(self, niche: Niche) -> NicheEcoResult:
        query = f"ytsearch{self._cfg.search_count}:{niche.canonical_name}"
        items = await self._adapter.collect(query)

        seen_channels: dict[str, dict] = {}
        for item in items:
            meta = getattr(item, "metadata", {}) or {}
            channel_id = meta.get("channel_id") or getattr(item, "author", None)
            if not channel_id:
                continue
            if channel_id in seen_channels:
                continue
            seen_channels[channel_id] = {
                "channel": channel_id,
                "name": getattr(item, "author", None),
                "follower_count": meta.get("follower_count"),
            }

        total = len(seen_channels)
        in_band = 0
        channels_out: list[dict] = []
        for info in seen_channels.values():
            fc = info.get("follower_count")
            in_target = (
                fc is not None
                and self._cfg.min_followers <= fc <= self._cfg.max_followers
            )
            if in_target:
                in_band += 1
            channels_out.append({**info, "in_target_band": in_target})

        return NicheEcoResult(
            niche_id=niche.id,
            niche_name=niche.canonical_name,
            total_creators=total,
            target_band_creators=in_band,
            channels=channels_out,
        )

    async def _verified_niches(
        self, campaign_id: str,
    ) -> list[tuple[CampaignNiche, Niche]]:
        result = await self._session.execute(
            select(CampaignNiche)
            .options(selectinload(CampaignNiche.niche))
            .where(
                CampaignNiche.campaign_id == campaign_id,
                CampaignNiche.status == CampaignNicheStatus.VERIFIED,
            )
        )
        rows = list(result.scalars().all())
        return [(cn, cn.niche) for cn in rows]
