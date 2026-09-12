"""Scoring pipeline — clusters + signals → CreatorScore + OpportunityScore rows."""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import CreatorPlatformAccount
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember
from corp.core.models.intent import CommercialSignal, SignalLevel
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
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

    async def run(self, creator_id: str) -> ResearchRun:
        run = ResearchRun(
            creator_id=creator_id,
            status="running",
            config_snapshot={"pipeline": "scoring", "rule_version": SCORING_RULE_VERSION},
            prompt_versions={},
            model_versions={},
        )
        self._session.add(run)
        await self._session.flush()

        try:
            subscriber_count = await self._get_subscriber_count(creator_id)
            clusters = await self._load_clusters()

            opp_scores: list[OpportunityScore] = []
            for cluster in clusters:
                opp = await self._score_opportunity(
                    cluster, creator_id, subscriber_count, run.id
                )
                if opp is not None:
                    opp_scores.append(opp)

            await self._score_creator(creator_id, opp_scores, run.id)

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = datetime.now(timezone.utc)
            logger.exception("Scoring pipeline failed")
            raise
        finally:
            await self._session.flush()

        return run

    async def _load_clusters(self) -> list[ProblemCluster]:
        result = await self._session.execute(select(ProblemCluster))
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
            select(CommercialSignal).where(
                CommercialSignal.problem_cluster_id == cluster_id
            )
        )
        return result.scalar_one_or_none()

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
        signal_confidence = signal.confidence if signal else 0.0

        components = {
            "audience_problem_frequency": score_audience_problem_frequency(cluster.frequency),
            "recency_trend": score_recency_trend(cluster.recency_score),
            "commercial_intent_strength": score_commercial_intent(signal_level, signal_confidence),
            "evidence_depth": score_evidence_depth(member_count),
            "creator_reach": score_creator_reach(subscriber_count),
            "competition_saturation": score_competition_saturation(),
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
