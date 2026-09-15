"""Niche selection (Slice 13).

The final step of the niche pipeline: rank VERIFIED, qualified niches by
``qualification_score`` and mark the winners SELECTED (creator discovery
proceeds only for these). Niches that clear the score/confidence thresholds
but miss the top-N cap, or fail a threshold, are marked REJECTED with a
rationale — a campaign's niche list is meant to reach a terminal decision,
not stay VERIFIED forever.

Deterministic: same ranked inputs -> same selection. Ties broken by
canonical_name so results are reproducible without depending on insertion
order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

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

PIPELINE = "niche_selection"


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    top_n: int = 5
    min_score: float = 0.0
    min_confidence: float = 0.0


class NicheSelector:
    def __init__(
        self,
        session: AsyncSession,
        config: SelectionConfig | None = None,
    ) -> None:
        self._session = session
        self._cfg = config or SelectionConfig()

    async def select(self, campaign_id: str) -> ResearchRun:
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "top_n": self._cfg.top_n,
                "min_score": self._cfg.min_score,
                "min_confidence": self._cfg.min_confidence,
            },
            prompt_versions={},
            model_versions={},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_SELECTION,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()

        try:
            candidates = await self._qualified_niches(campaign_id)
            ranked = sorted(
                candidates,
                key=lambda pair: (
                    -(pair[0].qualification_score or 0.0),
                    pair[1].canonical_name,
                ),
            )

            results: list[dict] = []
            selected_count = 0
            for rank, (cn, niche) in enumerate(ranked, start=1):
                score = cn.qualification_score or 0.0
                confidence = cn.confidence or 0.0

                if score < self._cfg.min_score:
                    reason = f"score {score:.4f} below minimum {self._cfg.min_score:.4f}"
                    cn.status = CampaignNicheStatus.REJECTED
                    cn.selected = False
                    cn.rationale = reason
                    selected = False
                elif confidence < self._cfg.min_confidence:
                    reason = (
                        f"confidence {confidence:.4f} below minimum "
                        f"{self._cfg.min_confidence:.4f}"
                    )
                    cn.status = CampaignNicheStatus.REJECTED
                    cn.selected = False
                    cn.rationale = reason
                    selected = False
                elif selected_count < self._cfg.top_n:
                    reason = f"ranked #{rank} of {len(ranked)} by qualification_score"
                    cn.status = CampaignNicheStatus.SELECTED
                    cn.selected = True
                    cn.rationale = reason
                    selected = True
                    selected_count += 1
                else:
                    reason = (
                        f"ranked #{rank} of {len(ranked)}, outside top {self._cfg.top_n}"
                    )
                    cn.status = CampaignNicheStatus.REJECTED
                    cn.selected = False
                    cn.rationale = reason
                    selected = False

                await self._session.flush()
                stats.ok()
                results.append({
                    "niche": niche.canonical_name,
                    "rank": rank,
                    "score": score,
                    "confidence": confidence,
                    "selected": selected,
                    "rationale": reason,
                })
                logger.info(
                    "Niche %r rank=%d score=%.4f selected=%s",
                    niche.canonical_name, rank, score, selected,
                )

            stats.extra.update(
                niches_ranked=len(ranked),
                selected=selected_count,
                rejected=len(ranked) - selected_count,
                results=results,
            )
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception(
                "Niche selection failed for campaign %s", campaign_id,
            )
            raise

    async def _qualified_niches(
        self, campaign_id: str,
    ) -> list[tuple[CampaignNiche, Niche]]:
        result = await self._session.execute(
            select(CampaignNiche)
            .options(selectinload(CampaignNiche.niche))
            .where(
                CampaignNiche.campaign_id == campaign_id,
                CampaignNiche.status == CampaignNicheStatus.VERIFIED,
                CampaignNiche.qualification_score.is_not(None),
            )
        )
        rows = list(result.scalars().all())
        return [(cn, cn.niche) for cn in rows]
