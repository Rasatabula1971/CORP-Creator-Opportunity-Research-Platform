"""Shared read queries used by multiple niche-pipeline stages."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.niche import Niche


async def verified_niches(
    session: AsyncSession, campaign_id: str,
) -> list[tuple[CampaignNiche, Niche]]:
    result = await session.execute(
        select(CampaignNiche)
        .options(selectinload(CampaignNiche.niche))
        .where(
            CampaignNiche.campaign_id == campaign_id,
            CampaignNiche.status == CampaignNicheStatus.VERIFIED,
        )
    )
    rows = list(result.scalars().all())
    return [(cn, cn.niche) for cn in rows]
