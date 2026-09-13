"""Scoring pipeline — clusters + signals → CreatorScore + OpportunityScore rows."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import CreatorPlatformAccount, CreatorStatus
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember
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
from corp.workers.intelligence.runs import (
    PipelineStats,
    active_clusters_for_creator,
    fail_run,
    finish_run,
    stage,
    start_run,
    supersede,
)

logger = logging.getLogger(__name__)

SCORING_RULE_VERSION = "scoring_v1"


class ScoringPipeline:
    """Scores every active ProblemCluster for a creator, then aggregates per creator.

    Each run supersedes the creator's previous active scores. Old rows stay
    for audit; reads filter on ``superseded_at IS NULL``.
    """

    def __init__(
        self,
        session: AsyncSession,
        rules_path: str = "rules/scoring.yaml",
    ) -> None:
        self._session = session
        self._rules = load_scoring_rules(rules_path)
        self._weights: dict[str, float] = self._rules.get("weights", {})

    async def run(self, creator_id: str) -> ResearchRun:
        run = await start_run(
            self._session,
            pipeline="scoring",
            creator_id=creator_id,
            config={"rule_version": SCORING_RULE_VERSION},
        )
        stats = PipelineStats()

        try:
            async with stage(
                self._session,
                creator_id,
                working=CreatorStatus.SCORING,
                done=CreatorStatus.SCORED,
            ):
                subscriber_count = await self._get_subscriber_count(creator_id)
                source_count = await self._get_source_count(creator_id)
                clusters = await active_clusters_for_creator(self._session, creator_id)

                await supersede(
                    self._session, OpportunityScore, OpportunityScore.creator_id == creator_id
                )
                await supersede(self._session, CreatorScore, CreatorScore.creator_id == creator_id)

                opp_scores: list[OpportunityScore] = []
                for cluster in clusters:
                    opp = await self._score_opportunity(
                        cluster, creator_id, subscriber_count, source_count, run.id
                    )
                    opp_scores.append(opp)
                    stats.ok()

                await self._score_creator(creator_id, opp_scores, source_count, run.id)
                stats.extra["opportunities"] = len(opp_scores)
                await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Scoring pipeline failed")
            raise

        return run

    # ── Lookups ──────────────────────────────────────────────────────

    async def _get_subscriber_count(self, creator_id: str) -> int | None:
        result = await self._session.execute(
            select(func.max(CreatorPlatformAccount.subscriber_count)).where(
                CreatorPlatformAccount.creator_id == creator_id
            )
        )
        return result.scalar()

    async def _get_signal(self, cluster_id: str) -> CommercialSignal | None:
        """Newest active signal for a cluster."""
        result = await self._session.execute(
            select(CommercialSignal)
            .where(
                CommercialSignal.problem_cluster_id == cluster_id,
                CommercialSignal.superseded_at.is_(None),
            )
            .order_by(CommercialSignal.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_member_count(self, cluster_id: str) -> int:
        result = await self._session.execute(
            select(func.count()).where(ProblemClusterMember.cluster_id == cluster_id)
        )
        return result.scalar() or 0

    async def _get_source_count(self, creator_id: str) -> int:
        result = await self._session.execute(
            select(func.count(func.distinct(CreatorPlatformAccount.platform))).where(
                CreatorPlatformAccount.creator_id == creator_id
            )
        )
        return result.scalar() or 0

    # ── Scoring ──────────────────────────────────────────────────────

    async def _score_opportunity(
        self,
        cluster: ProblemCluster,
        creator_id: str,
        subscriber_count: int | None,
        source_count: int,
        run_id: str,
    ) -> OpportunityScore:
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
        band = compute_confidence_band(
            source_count=source_count,
            evidence_depth=member_count,
            days_since_newest=_days_from_recency(cluster.recency_score),
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
        source_count: int,
        run_id: str,
    ) -> CreatorScore:
        if not opp_scores:
            components = {k: 0.0 for k in self._weights}
        else:
            components = {
                dim: max(o.component_scores.get(dim, 0.0) for o in opp_scores)
                for dim in self._weights
            }

        aggregate = compute_score(components, self._weights)
        computed = compute_hash(components, SCORING_RULE_VERSION)

        total_evidence = 0
        for o in opp_scores:
            total_evidence += await self._get_member_count(o.problem_cluster_id)

        best_recency = max(
            (o.component_scores.get("recency_trend", 0.0) for o in opp_scores),
            default=0.0,
        )
        band = compute_confidence_band(
            source_count=source_count,
            evidence_depth=total_evidence,
            days_since_newest=_days_from_recency(best_recency),
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


def _days_from_recency(recency_score: float) -> int:
    """Invert the 0..1 recency score back to an approximate age in days."""
    return int((1.0 - recency_score) * 365) if recency_score < 1.0 else 0
