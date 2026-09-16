"""Niche qualification scoring pipeline (Slice 12).

For each VERIFIED CampaignNiche in a campaign, compute a deterministic
qualification score from evidence depth, author diversity, ecosystem size,
target-band density, and specificity. Populates ``qualification_score``,
``confidence``, and ``research_completeness`` on the CampaignNiche row.

No LLM, no API key, no cost. Weights are YAML-driven
(``rules/niche_qualification.yaml``).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.niche import Niche
from corp.core.models.niche_candidate import NicheCandidate, NicheCandidateStatus
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.core.scoring.niche_qualification import (
    NicheInput,
    load_rules,
    qualify,
)
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    start_run,
)

logger = logging.getLogger(__name__)

PIPELINE = "niche_qualification"


class NicheQualifier:
    def __init__(
        self,
        session: AsyncSession,
        rules_path: str,
    ) -> None:
        self._session = session
        self._rules = load_rules(rules_path)

    async def qualify_campaign(self, campaign_id: str) -> ResearchRun:
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={"rules_version": self._rules.get("version", "unknown")},
            prompt_versions={},
            model_versions={},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_QUALIFICATION,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()

        try:
            niches = await self._verified_niches(campaign_id)
            results: list[dict] = []

            for cn, niche in niches:
                candidate = await self._promoted_candidate(
                    campaign_id, niche.id,
                )
                inp = NicheInput(
                    evidence_count=candidate.evidence_count if candidate else 0,
                    author_count=candidate.author_count if candidate else 0,
                    is_broad_domain=(
                        candidate.is_broad_domain if candidate else False
                    ),
                    creator_count_observed=cn.creator_count_observed,
                    target_band_creator_count=(
                        cn.target_band_creator_count or 0
                    ),
                )
                is_verified = cn.status == CampaignNicheStatus.VERIFIED
                result = qualify(inp, is_verified, self._rules)

                cn.qualification_score = result.qualification_score
                cn.confidence = result.confidence
                cn.research_completeness = result.research_completeness
                await self._session.flush()
                stats.ok()

                results.append({
                    "niche": niche.canonical_name,
                    "qualification_score": result.qualification_score,
                    "confidence": result.confidence,
                    "research_completeness": result.research_completeness,
                    "components": result.components,
                })
                logger.info(
                    "Niche %r: score=%.4f confidence=%.4f completeness=%.4f",
                    niche.canonical_name,
                    result.qualification_score,
                    result.confidence,
                    result.research_completeness,
                )

            stats.extra.update(
                niches_scored=len(niches),
                results=results,
            )
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception(
                "Niche qualification failed for campaign %s", campaign_id,
            )
            raise

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

    async def _promoted_candidate(
        self, campaign_id: str, niche_id: str,
    ) -> NicheCandidate | None:
        result = await self._session.execute(
            select(NicheCandidate)
            .where(
                NicheCandidate.campaign_id == campaign_id,
                NicheCandidate.niche_id == niche_id,
                NicheCandidate.status == NicheCandidateStatus.PROMOTED,
                NicheCandidate.superseded_at.is_(None),
            )
            .order_by(NicheCandidate.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
