"""Scoring pipeline — clusters + signals → CreatorScore + OpportunityScore rows."""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.competitive import Competitor
from corp.core.models.creator import Creator, CreatorPlatformAccount, CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember, ProblemObservation
from corp.core.models.intent import CommercialSignal, SignalLevel
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.core.scoring.confidence import compute_confidence_band
from corp.core.scoring.engine import (
    compute_hash,
    compute_score,
    load_scoring_rules,
    score_audience_problem_frequency,
    score_commercial_intent,
    score_competition_saturation,
    score_creator_reach,
    score_evidence_depth,
    score_recency_trend,
)

logger = logging.getLogger(__name__)

SCORING_RULE_VERSION = "scoring_v1"


class ScoringPipeline:
    """Scores every ProblemCluster as an opportunity, then aggregates per creator."""

    def __init__(
        self,
        session: AsyncSession,
        rules_path: str = "rules/scoring.yaml",
    ) -> None:
        self._session = session
        self._rules = load_scoring_rules(rules_path)
        self._weights: dict[str, float] = self._rules.get("weights", {})
        self._confidence_thresholds: dict | None = self._rules.get("confidence_thresholds")

    async def run(self, creator_id: str) -> ResearchRun:
        run = ResearchRun(
            creator_id=creator_id,
            status="running",
            started_at=datetime.now(timezone.utc),
            config_snapshot={"pipeline": "scoring", "rule_version": SCORING_RULE_VERSION},
            prompt_versions={},
            model_versions={},
        )
        self._session.add(run)
        await self._session.flush()

        await self._transition_status(creator_id, CreatorStatus.SCORING)

        try:
            run.record_step("load_data", "running")
            await self._session.flush()
            subscriber_count = await self._get_subscriber_count(creator_id)
            clusters = await self._load_clusters(creator_id)
            run.record_step("load_data", "completed", detail={"cluster_count": len(clusters)})

            run.record_step("score_opportunities", "running")
            await self._session.flush()
            opp_scores: list[OpportunityScore] = []
            for cluster in clusters:
                opp = await self._score_opportunity(
                    cluster, creator_id, subscriber_count, run.id
                )
                if opp is not None:
                    opp_scores.append(opp)
            run.record_step("score_opportunities", "completed", detail={"count": len(opp_scores)})

            run.record_step("score_creator", "running")
            await self._session.flush()
            await self._score_creator(creator_id, opp_scores, run.id)
            run.record_step("score_creator", "completed")

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            await self._transition_status(creator_id, CreatorStatus.SCORED)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = datetime.now(timezone.utc)
            logger.exception("Scoring pipeline failed")
            raise
        finally:
            await self._session.flush()

        return run

    async def _transition_status(self, creator_id: str, status: CreatorStatus) -> None:
        result = await self._session.execute(
            select(Creator).where(Creator.id == creator_id)
        )
        creator = result.scalars().first()
        if creator:
            creator.status = status
            await self._session.flush()

    async def _load_clusters(self, creator_id: str) -> list[ProblemCluster]:
        cluster_ids_subq = (
            select(ProblemClusterMember.cluster_id)
            .join(ProblemObservation, ProblemClusterMember.observation_id == ProblemObservation.id)
            .join(Evidence, ProblemObservation.evidence_id == Evidence.id)
            .join(ResearchRun, Evidence.research_run_id == ResearchRun.id)
            .where(ResearchRun.creator_id == creator_id)
            .distinct()
        )
        result = await self._session.execute(
            select(ProblemCluster).where(ProblemCluster.id.in_(cluster_ids_subq))
        )
        return list(result.scalars().all())

    async def _get_subscriber_count(self, creator_id: str) -> int | None:
        result = await self._session.execute(
            select(func.max(CreatorPlatformAccount.subscriber_count)).where(
                CreatorPlatformAccount.creator_id == creator_id
            )
        )
        return result.scalar()

    async def _get_signal(self, cluster_id: str) -> CommercialSignal | None:
        result = await self._session.execute(
            select(CommercialSignal)
            .where(CommercialSignal.problem_cluster_id == cluster_id)
            .order_by(CommercialSignal.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def _get_member_count(self, cluster_id: str) -> int:
        result = await self._session.execute(
            select(func.count()).where(
                ProblemClusterMember.cluster_id == cluster_id
            )
        )
        return result.scalar() or 0

    async def _get_source_count(self, creator_id: str) -> int:
        result = await self._session.execute(
            select(func.count(func.distinct(CreatorPlatformAccount.platform))).where(
                CreatorPlatformAccount.creator_id == creator_id
            )
        )
        return result.scalar() or 0

    async def _get_competitor_strengths(self, cluster_id: str) -> list:
        result = await self._session.execute(
            select(Competitor.strength).where(Competitor.problem_cluster_id == cluster_id)
        )
        return list(result.scalars().all())

    async def _score_opportunity(
        self,
        cluster: ProblemCluster,
        creator_id: str,
        subscriber_count: int | None,
        run_id: str,
    ) -> OpportunityScore | None:
        signal = await self._get_signal(cluster.id)
        member_count = await self._get_member_count(cluster.id)

        signal_level = signal.signal_level if signal else SignalLevel.WEAK
        signal_confidence = signal.confidence if signal and signal.confidence is not None else 0.0
        competitor_strengths = await self._get_competitor_strengths(cluster.id)

        components = {
            "audience_problem_frequency": score_audience_problem_frequency(cluster.frequency),
            "recency_trend": score_recency_trend(cluster.recency_score),
            "commercial_intent_strength": score_commercial_intent(signal_level, signal_confidence),
            "evidence_depth": score_evidence_depth(member_count),
            "creator_reach": score_creator_reach(subscriber_count),
            "competition_saturation": score_competition_saturation(competitor_strengths),
        }

        aggregate = compute_score(components, self._weights)
        computed = compute_hash(components, SCORING_RULE_VERSION)

        source_count = await self._get_source_count(creator_id)
        days_fresh = int((1.0 - cluster.recency_score) * 365) if cluster.recency_score < 1.0 else 0
        band = compute_confidence_band(
            source_count=source_count,
            evidence_depth=member_count,
            days_since_newest=days_fresh,
            single_source=source_count <= 1,
            thresholds=self._confidence_thresholds,
        )

        opp = OpportunityScore(
            creator_id=creator_id,
            problem_cluster_id=cluster.id,
            component_scores=components,
            aggregate_score=aggregate,
            computed_hash=computed,
            confidence_band=band,
            rule_version=SCORING_RULE_VERSION,
            model_version="deterministic",
            research_run_id=run_id,
        )
        self._session.add(opp)
        await self._session.flush()
        return opp

    async def _score_creator(
        self,
        creator_id: str,
        opp_scores: list[OpportunityScore],
        run_id: str,
    ) -> CreatorScore:
        if not opp_scores:
            components = {k: 0.0 for k in self._weights}
        else:
            components = {}
            for dim in self._weights:
                values = [o.component_scores.get(dim, 0.0) for o in opp_scores]
                components[dim] = max(values)

        aggregate = compute_score(components, self._weights)
        computed = compute_hash(components, SCORING_RULE_VERSION)

        source_count = await self._get_source_count(creator_id)
        total_evidence = sum(
            await self._get_member_count(o.problem_cluster_id) for o in opp_scores
        ) if opp_scores else 0

        best_recency = max(
            (o.component_scores.get("recency_trend", 0.0) for o in opp_scores),
            default=0.0,
        )
        days_fresh = int((1.0 - best_recency) * 365) if best_recency < 1.0 else 0

        band = compute_confidence_band(
            source_count=source_count,
            evidence_depth=total_evidence,
            days_since_newest=days_fresh,
            single_source=source_count <= 1,
            thresholds=self._confidence_thresholds,
        )

        creator_score = CreatorScore(
            creator_id=creator_id,
            component_scores=components,
            aggregate_score=aggregate,
            computed_hash=computed,
            confidence_band=band,
            rule_version=SCORING_RULE_VERSION,
            model_version="deterministic",
            research_run_id=run_id,
        )
        self._session.add(creator_score)
        await self._session.flush()
        return creator_score
