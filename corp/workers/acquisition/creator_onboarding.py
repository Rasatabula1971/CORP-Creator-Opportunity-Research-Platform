"""Creator onboarding from selected niches (Slice 14).

The last step before the per-creator research pipeline (`collect` /
`intelligence` / `intent` / `research`) has anything to work on: turn the
ecosystem search hits for each SELECTED CampaignNiche into real ``Creator``
rows, so a human (or a later automation) can point the existing pipeline at
them.

Get-or-create throughout — re-running onboarding for the same niche never
duplicates a Creator (identity is the platform handle, via the existing
unique ``(platform, handle)`` index on CreatorPlatformAccount) or a
CreatorNiche link (unique on ``(creator_id, niche_id)``, from Slice 4). A
re-observed link just advances ``last_observed_at``.
"""

from __future__ import annotations

import logging
from typing import Any
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.niche import Niche
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.workers.intelligence.ecosystem_estimator import ChannelEnricher, SearchAdapter
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    start_run,
)

logger = logging.getLogger(__name__)

PIPELINE = "creator_onboarding"

PLATFORM = "youtube"


def _is_enrichable_channel_id(channel_id: str) -> bool:
    """Only real YouTube channel IDs (``UC`` + 22 chars) can be looked up via the
    Data API's ``channels.list``. ``@handle`` fallbacks and display names cannot."""
    return channel_id.startswith("UC") and len(channel_id) == 24


@dataclass(frozen=True, slots=True)
class OnboardConfig:
    search_count: int = 20
    max_creators_per_niche: int = 10
    min_followers: int | None = None
    max_followers: int | None = None


class CreatorOnboarder:
    def __init__(
        self,
        adapter: SearchAdapter,
        session: AsyncSession,
        config: OnboardConfig | None = None,
        enricher: ChannelEnricher | None = None,
    ) -> None:
        self._adapter = adapter
        self._session = session
        self._cfg = config or OnboardConfig()
        self._enricher = enricher

    async def onboard(self, campaign_id: str) -> ResearchRun:
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "search_count": self._cfg.search_count,
                "max_creators_per_niche": self._cfg.max_creators_per_niche,
                "min_followers": self._cfg.min_followers,
                "max_followers": self._cfg.max_followers,
            },
            prompt_versions={},
            model_versions={},
            scope=RunScope.NICHE,
            run_type=RunType.CREATOR_ONBOARDING,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()

        try:
            niches = await self._selected_niches(campaign_id)

            # Pass 1 — search every niche (yt-dlp; no reliable subscriber counts).
            niche_channels: list[tuple[Niche, dict[str, dict[str, Any]]]] = [
                (niche, await self._search_niche_raw(niche)) for niche in niches
            ]

            # Pass 2 — one batched Data API enrichment for the whole campaign.
            # A channel found in several niches is looked up once, and
            # channels.list bills 1 quota unit per 50 IDs, so this is the
            # cheapest way to get real subscriber counts.
            counts = await self._enrich_all(niche_channels)

            results: list[dict[str, Any]] = []
            creators_created = 0
            creators_linked = 0

            # Pass 3 — apply real counts, filter to the follower band, cap, create.
            for niche, raw in niche_channels:
                channels = self._filter_and_cap(raw, counts)
                niche_created = niche_linked = 0

                for channel_id, info in channels.items():
                    creator, is_new = await self._get_or_create_creator(
                        channel_id, info, niche,
                    )
                    await self._get_or_create_link(
                        creator.id, niche.id, run.id,
                    )
                    if is_new:
                        creators_created += 1
                        niche_created += 1
                    else:
                        creators_linked += 1
                        niche_linked += 1
                    stats.ok()

                results.append({
                    "niche": niche.canonical_name,
                    "channels_found": len(channels),
                    "creators_created": niche_created,
                    "creators_linked": niche_linked,
                })
                logger.info(
                    "Niche %r: %d channels, %d new creators, %d linked",
                    niche.canonical_name, len(channels), niche_created, niche_linked,
                )

            stats.extra.update(
                niches_processed=len(niches),
                creators_created=creators_created,
                creators_linked=creators_linked,
                channels_enriched=len(counts),
                results=results,
            )
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception(
                "Creator onboarding failed for campaign %s", campaign_id,
            )
            raise

    async def _search_niche_raw(self, niche: Niche) -> dict[str, dict[str, Any]]:
        """Search a niche and return every unique channel (no band filter, no cap).

        Filtering and capping happen after enrichment, so we must not drop or
        truncate here — otherwise the follower band would be applied against
        yt-dlp's missing counts and the wrong channels would survive.
        """
        query = f"ytsearch{self._cfg.search_count}:{niche.canonical_name}"
        items = await self._adapter.collect(query)

        channels: dict[str, dict[str, Any]] = {}
        for item in items:
            meta = getattr(item, "metadata", {}) or {}
            # Prefer yt-dlp's stable identifiers (UC channel_id, then @handle) over
            # the author display name: it becomes CreatorPlatformAccount.handle,
            # which later gets fed straight into YtDlpAdapter.profile_url() to
            # re-collect content for this creator — a display name (spaces,
            # unicode, doesn't match the real handle) 404s there.
            channel_id = (
                meta.get("channel_id")
                or meta.get("channel_handle")
                or getattr(item, "author", None)
            )
            if not channel_id or channel_id in channels:
                continue
            channels[channel_id] = {
                "name": getattr(item, "author", None) or channel_id,
                "follower_count": meta.get("follower_count"),
            }
        return channels

    async def _enrich_all(
        self, niche_channels: list[tuple[Niche, dict[str, dict[str, Any]]]],
    ) -> dict[str, int | None]:
        """One deduplicated, batched subscriber-count lookup for the whole run."""
        if self._enricher is None:
            return {}
        ids = sorted({
            cid
            for _, channels in niche_channels
            for cid in channels
            if _is_enrichable_channel_id(cid)
        })
        if not ids:
            return {}
        try:
            counts = await self._enricher.get_subscriber_counts(ids)
        except Exception:
            logger.warning(
                "YouTube API enrichment failed; onboarding without subscriber counts",
                exc_info=True,
            )
            return {}
        logger.info("Enriched %d/%d channels with subscriber counts", len(counts), len(ids))
        return counts

    def _filter_and_cap(
        self, raw: dict[str, dict[str, Any]], counts: dict[str, int | None],
    ) -> dict[str, dict[str, Any]]:
        channels: dict[str, dict[str, Any]] = {}
        for channel_id, info in raw.items():
            if len(channels) >= self._cfg.max_creators_per_niche:
                break
            follower_count = counts.get(channel_id, info.get("follower_count"))
            if not self._in_band(follower_count):
                continue
            channels[channel_id] = {**info, "follower_count": follower_count}
        return channels

    def _in_band(self, follower_count: int | None) -> bool:
        if follower_count is None:
            return True  # unknown reach never blocks onboarding
        if self._cfg.min_followers is not None and follower_count < self._cfg.min_followers:
            return False
        if self._cfg.max_followers is not None and follower_count > self._cfg.max_followers:
            return False
        return True

    async def _get_or_create_creator(
        self, channel_id: str, info: dict[str, Any], niche: Niche,
    ) -> tuple[Creator, bool]:
        result = await self._session.execute(
            select(CreatorPlatformAccount)
            .options(selectinload(CreatorPlatformAccount.creator))
            .where(
                CreatorPlatformAccount.platform == PLATFORM,
                CreatorPlatformAccount.handle == channel_id,
            )
        )
        account = result.scalar_one_or_none()
        if account is not None:
            return account.creator, False

        creator = Creator(
            name=info["name"],
            niche=niche.canonical_name,
            discovery_source="ecosystem_search",
        )
        self._session.add(creator)
        await self._session.flush()

        self._session.add(CreatorPlatformAccount(
            creator_id=creator.id,
            platform=PLATFORM,
            handle=channel_id,
            external_id=channel_id,
            subscriber_count=info.get("follower_count"),
        ))
        await self._session.flush()
        return creator, True

    async def _get_or_create_link(
        self, creator_id: str, niche_id: str, run_id: str,
    ) -> bool:
        result = await self._session.execute(
            select(CreatorNiche).where(
                CreatorNiche.creator_id == creator_id,
                CreatorNiche.niche_id == niche_id,
            )
        )
        link = result.scalar_one_or_none()
        if link is not None:
            link.last_observed_at = datetime.now(UTC)
            await self._session.flush()
            return False

        self._session.add(CreatorNiche(
            creator_id=creator_id,
            niche_id=niche_id,
            discovery_run_id=run_id,
        ))
        await self._session.flush()
        return True

    async def _selected_niches(self, campaign_id: str) -> list[Niche]:
        result = await self._session.execute(
            select(CampaignNiche)
            .options(selectinload(CampaignNiche.niche))
            .where(
                CampaignNiche.campaign_id == campaign_id,
                CampaignNiche.status == CampaignNicheStatus.SELECTED,
            )
        )
        rows = list(result.scalars().all())
        return [cn.niche for cn in rows]
