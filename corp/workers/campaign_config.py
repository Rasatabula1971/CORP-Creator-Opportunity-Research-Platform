"""Campaign row -> per-stage worker configuration.

``Campaign`` carries the knobs a person sets when they create a campaign
(``target_niche_count``, ``initial_creators_per_niche``, the creator
follower band, ``human_gate_capacity``). Until this module existed those
values were stored and echoed back by the API but never read by any
stage: the automated chain in ``discovery_scan._advance_campaign_to_gate``
and the manual ``POST /campaigns/{id}/{stage}`` branches in ``api/jobs``
both constructed every worker with its dataclass defaults, so every
campaign behaved like the default one no matter what its row said.

One mapping here, used by both callers, so the two cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.creator_niche import CreatorNiche
from corp.workers.acquisition.creator_onboarding import OnboardConfig
from corp.workers.campaign_research import BatchConfig
from corp.workers.intelligence.ecosystem_estimator import EcoConfig
from corp.workers.intelligence.niche_selection import SelectionConfig


class CampaignNotFoundError(LookupError):
    """No Campaign row with the given id."""


async def load_campaign(session: AsyncSession, campaign_id: str) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
    return campaign


def selection_config(campaign: Campaign) -> SelectionConfig:
    """``target_niche_count`` is the campaign's SELECTED cap (cumulative,
    see NicheSelector); score/confidence floors stay at their defaults."""
    return SelectionConfig(top_n=campaign.target_niche_count)


def eco_config(campaign: Campaign) -> EcoConfig:
    """The campaign's follower band is what "target band" means when the
    ecosystem estimate counts how many creators a niche has in reach."""
    return EcoConfig(
        min_followers=campaign.creator_min_followers,
        max_followers=campaign.creator_max_followers,
    )


def onboard_config(campaign: Campaign) -> OnboardConfig:
    """Same band for the creators actually onboarded, and
    ``initial_creators_per_niche`` as the per-niche cap.

    The search fetches more results than the cap so the band filter has
    something to drop without starving the niche; the default 20-for-10
    ratio is kept for larger caps.
    """
    per_niche = campaign.initial_creators_per_niche
    return OnboardConfig(
        search_count=max(OnboardConfig().search_count, per_niche * 2),
        max_creators_per_niche=per_niche,
        min_followers=campaign.creator_min_followers,
        max_followers=campaign.creator_max_followers,
    )


async def human_gate_occupancy(session: AsyncSession, campaign_id: str) -> int:
    """Creators of this campaign's SELECTED niches currently waiting at
    the human decision gate (Creator.status mirrors the creator's pending
    dossiers -- see routes_ops.mirror_creator_status)."""
    result = await session.execute(
        select(func.count(func.distinct(Creator.id)))
        .select_from(Creator)
        .join(CreatorNiche, CreatorNiche.creator_id == Creator.id)
        .join(CampaignNiche, CampaignNiche.niche_id == CreatorNiche.niche_id)
        .where(
            CampaignNiche.campaign_id == campaign_id,
            CampaignNiche.status == CampaignNicheStatus.SELECTED,
            Creator.status == CreatorStatus.HUMAN_REVIEW,
        )
    )
    return int(result.scalar_one())


async def batch_config(session: AsyncSession, campaign: Campaign) -> BatchConfig:
    """Research only as many creators as the human gate has room for.

    ``human_gate_capacity`` bounds how many dossiers can be waiting on a
    decision at once; every researched creator lands there, so a batch is
    limited to the capacity minus the creators already waiting. Zero
    headroom means the batch runs and researches nobody (rather than
    skipping the stage, so the run row still records why).
    """
    waiting = await human_gate_occupancy(session, campaign.id)
    headroom = max(0, campaign.human_gate_capacity - waiting)
    return BatchConfig(limit=headroom)


@dataclass(frozen=True, slots=True)
class CampaignStageConfigs:
    selection: SelectionConfig
    ecosystem: EcoConfig
    onboarding: OnboardConfig


def stage_configs(campaign: Campaign) -> CampaignStageConfigs:
    """The DB-free configs in one bundle; ``batch_config`` is separate
    because it has to count gate occupancy at the moment research starts
    (after onboard has run), not when the chain begins."""
    return CampaignStageConfigs(
        selection=selection_config(campaign),
        ecosystem=eco_config(campaign),
        onboarding=onboard_config(campaign),
    )
