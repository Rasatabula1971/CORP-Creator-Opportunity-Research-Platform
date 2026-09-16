"""Creator ecosystem size estimator (Slice 11).

For each VERIFIED niche in a campaign, run a yt-dlp search to discover how
many unique creator channels are active in the niche. Populates
``creator_count_observed`` and ``target_band_creator_count`` on the
CampaignNiche row.

Discovery uses yt-dlp (free, no API key). When ``YOUTUBE_API_KEY`` is set,
a second-pass enrichment resolves each unique channel via the YouTube Data
API v3 ``channels().list(part="statistics")`` to get real subscriber counts
(1 quota unit per 50 channels — negligible against the 10K/day free tier).

``target_band_creator_count`` is the subset of observed creators whose
subscriber count falls within a configurable band (default 10K–200K),
the sweet spot for partnership outreach.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

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


class ChannelEnricher(Protocol):
    """Resolve channel IDs to subscriber counts."""

    async def get_subscriber_counts(
        self, channel_ids: list[str],
    ) -> dict[str, int | None]: ...


class YouTubeAPIEnricher:
    """Fetches real subscriber counts via YouTube Data API v3.

    Costs 1 quota unit per 50 channels. Batches automatically.
    """

    def __init__(
        self,
        api_key: str,
        service_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._factory = service_factory

    def _build_service(self) -> Any:
        if self._factory is not None:
            return self._factory()
        from googleapiclient.discovery import build
        return build("youtube", "v3", developerKey=self._api_key)

    async def get_subscriber_counts(
        self, channel_ids: list[str],
    ) -> dict[str, int | None]:
        if not channel_ids:
            return {}

        def _fetch() -> dict[str, int | None]:
            service = self._build_service()
            result: dict[str, int | None] = {}
            for i in range(0, len(channel_ids), 50):
                batch = channel_ids[i: i + 50]
                resp = (
                    service.channels()
                    .list(part="statistics", id=",".join(batch))
                    .execute()
                )
                for item in resp.get("items", []):
                    stats = item.get("statistics", {})
                    hidden = stats.get("hiddenSubscriberCount", False)
                    if hidden:
                        result[item["id"]] = None
                    else:
                        raw = stats.get("subscriberCount")
                        result[item["id"]] = int(raw) if raw else None
            return result

        return await asyncio.to_thread(_fetch)


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
        enricher: ChannelEnricher | None = None,
    ) -> None:
        self._adapter = adapter
        self._session = session
        self._cfg = config or EcoConfig()
        self._enricher = enricher

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
            # Prefer yt-dlp's stable identifiers (UC channel_id, then @handle) over
            # the author display name, which can't be turned back into a working
            # profile URL (spaces/unicode, doesn't match the real handle).
            channel_id = (
                meta.get("channel_id")
                or meta.get("channel_handle")
                or getattr(item, "author", None)
            )
            if not channel_id:
                continue
            if channel_id in seen_channels:
                continue
            seen_channels[channel_id] = {
                "channel": channel_id,
                "name": getattr(item, "author", None),
                "follower_count": meta.get("follower_count"),
            }

        if self._enricher and seen_channels:
            await self._enrich_subscriber_counts(seen_channels)

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

    async def _enrich_subscriber_counts(
        self, channels: dict[str, dict],
    ) -> None:
        ids = [
            cid for cid in channels
            if cid.startswith("UC") and len(cid) == 24
        ]
        if not ids:
            return
        try:
            counts = await self._enricher.get_subscriber_counts(ids)  # type: ignore[union-attr]
            for cid, count in counts.items():
                if cid in channels and count is not None:
                    channels[cid]["follower_count"] = count
            logger.info(
                "Enriched %d/%d channels with subscriber counts",
                len(counts), len(ids),
            )
        except Exception:
            logger.warning(
                "YouTube API enrichment failed; using yt-dlp counts only",
                exc_info=True,
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
