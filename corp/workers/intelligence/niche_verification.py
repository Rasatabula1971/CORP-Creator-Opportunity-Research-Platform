"""Niche verification (Slice 10, §7).

Candidate niches are advanced to ACTIVE when they pass evidence-quality
thresholds. The verification is deterministic — no LLM, no embedding — just
min-evidence, min-author, and a broad-domain gate.

A niche that fails any check stays at CANDIDATE with a rationale explaining
why. The CampaignNiche row is updated to VERIFIED (pass) or left at
DISCOVERED (fail) so per-campaign tracking stays accurate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.niche import Niche, NicheLifecycleStatus
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateStatus,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    start_run,
)

logger = logging.getLogger(__name__)

PIPELINE = "niche_verification"


@dataclass(frozen=True, slots=True)
class VerifyConfig:
    min_evidence: int = 5
    min_authors: int = 3
    reject_broad_domain: bool = True
    recheck_days: int = 90


@dataclass(slots=True)
class VerifyResult:
    niche_id: str
    niche_name: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


class NicheVerifier:
    def __init__(
        self,
        session: AsyncSession,
        config: VerifyConfig | None = None,
    ) -> None:
        self._session = session
        self._cfg = config or VerifyConfig()

    async def verify(self, campaign_id: str) -> ResearchRun:
        """Verify every CANDIDATE niche linked to the campaign."""
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "min_evidence": self._cfg.min_evidence,
                "min_authors": self._cfg.min_authors,
                "reject_broad_domain": self._cfg.reject_broad_domain,
            },
            prompt_versions={},
            model_versions={},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_DISCOVERY,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()

        try:
            candidates = await self._promoted_candidates(campaign_id)
            stats.extra["candidates_checked"] = len(candidates)

            verified = 0
            failed_verification = 0
            results: list[dict[str, Any]] = []

            for cand in candidates:
                niche = await self._session.get(Niche, cand.niche_id)
                if niche is None or niche.lifecycle_status != NicheLifecycleStatus.CANDIDATE:
                    stats.skip()
                    continue

                result = self._check(niche, cand)
                results.append({
                    "niche": niche.canonical_name,
                    "passed": result.passed,
                    "reasons": result.reasons,
                })

                if result.passed:
                    niche.lifecycle_status = NicheLifecycleStatus.ACTIVE
                    now = datetime.now(UTC)
                    niche.last_researched_at = now
                    niche.next_recheck_at = now + timedelta(days=self._cfg.recheck_days)
                    await self._update_campaign_niche(
                        campaign_id, niche.id, CampaignNicheStatus.VERIFIED
                    )
                    verified += 1
                    logger.info("Niche %r verified → ACTIVE", niche.canonical_name)
                else:
                    await self._update_campaign_niche(
                        campaign_id, niche.id, CampaignNicheStatus.DISCOVERED,
                        rationale="; ".join(result.reasons),
                    )
                    failed_verification += 1
                    logger.info(
                        "Niche %r failed verification: %s",
                        niche.canonical_name, "; ".join(result.reasons),
                    )

                await self._session.flush()
                stats.ok()

            stats.extra.update(
                verified=verified,
                failed_verification=failed_verification,
                results=results,
            )
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Verification failed for campaign %s", campaign_id)
            raise

    def _check(self, niche: Niche, cand: NicheCandidate) -> VerifyResult:
        reasons: list[str] = []

        if cand.evidence_count < self._cfg.min_evidence:
            reasons.append(
                f"evidence_count={cand.evidence_count} < {self._cfg.min_evidence}"
            )
        if cand.author_count < self._cfg.min_authors:
            reasons.append(
                f"author_count={cand.author_count} < {self._cfg.min_authors}"
            )
        if self._cfg.reject_broad_domain and cand.is_broad_domain:
            reasons.append("is_broad_domain=True")

        return VerifyResult(
            niche_id=niche.id,
            niche_name=niche.canonical_name,
            passed=len(reasons) == 0,
            reasons=reasons,
        )

    async def _promoted_candidates(self, campaign_id: str) -> list[NicheCandidate]:
        result = await self._session.execute(
            select(NicheCandidate)
            .where(
                NicheCandidate.campaign_id == campaign_id,
                NicheCandidate.status.in_(
                    [NicheCandidateStatus.PROMOTED, NicheCandidateStatus.MERGED]
                ),
                NicheCandidate.niche_id.isnot(None),
                NicheCandidate.superseded_at.is_(None),
            )
            .order_by(NicheCandidate.evidence_count.desc())
        )
        return list(result.scalars().all())

    async def _update_campaign_niche(
        self,
        campaign_id: str,
        niche_id: str,
        status: CampaignNicheStatus,
        *,
        rationale: str | None = None,
    ) -> None:
        result = await self._session.execute(
            select(CampaignNiche).where(
                CampaignNiche.campaign_id == campaign_id,
                CampaignNiche.niche_id == niche_id,
            )
        )
        cn = result.scalar_one_or_none()
        if cn is not None:
            cn.status = status
            if rationale is not None:
                cn.rationale = rationale
            await self._session.flush()
