"""Scoring pipeline (scoring_v2) — clusters + signals + snapshots → scores.

Every component is a pure function of stored rows, so the computed hash is
reproducible. Diagnostics (engagement, source mix, growth) are stored beside
the score but never hashed.
"""

import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.competitive import Competitor
from corp.core.models.content import AudienceInteraction, ContentItem
from corp.core.models.creator import CreatorPlatformAccount, CreatorStatus
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.evidence import ComplianceStatus, Evidence, EvidenceType
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal, SignalLevel
from corp.core.models.metrics import MetricsSnapshot
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.core.scoring.confidence import compute_confidence_band
from corp.core.scoring.engine import (
    compute_hash,
    compute_score,
    growth_ratio,
    load_scoring_rules,
    score_audience_dissatisfaction,
    score_audience_problem_frequency,
    score_commercial_intent,
    score_competition_saturation,
    score_competitor_saturation,
    score_creator_content_alignment,
    score_creator_reach,
    score_cross_platform_consistency,
    score_engagement_velocity,
    score_evidence_depth,
    score_external_demand_strength,
    score_purchase_intent,
    score_recency_trend,
    score_solution_saturation,
    weighted_evidence_count,
)
from corp.core.scoring.text import containment, jaccard, tokens
from corp.warmstore.sync import mirror_scores
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

SCORING_RULE_VERSION = "scoring_v2"
ALIGNMENT_THRESHOLD = 0.2  # jaccard between a creator observation and the cluster
COMMERCE_KINDS = {"shop", "course", "product", "membership"}

# The four T21 components read only these evidence types; the rest (PROBLEM,
# PLANNING_INTENT, MONETISATION) never inform them, so there's no reason to
# pull their (often much larger) raw_text volume into memory per creator.
_MARKET_EVIDENCE_TYPES = (
    EvidenceType.TREND,
    EvidenceType.SEARCH_INTENT,
    EvidenceType.SOLUTION,
    EvidenceType.TRANSACTION,
    EvidenceType.DISSATISFACTION,
)


@dataclass
class CreatorContext:
    """Everything about a creator the per-cluster scoring needs, loaded once."""

    subscriber_count: int | None
    audience_platforms: list[str]  # platforms with audience content (not "web")
    creator_observation_tokens: list[frozenset[str]]
    commerce_page_tokens: list[frozenset[str]]  # pages tagged with a commerce kind
    commerce_signal_count: int
    monetisation: dict[str, int]
    engagement_rate_by_platform: dict[str, float]
    follower_growth: float | None
    # Tokenized raw_text of each niche-discovery evidence row, by evidence
    # type — kept per-row (not pre-counted) so _score_opportunity can count
    # only the rows relevant to each specific cluster's text, instead of
    # crediting every cluster with every market signal gathered anywhere in
    # the creator's niches (see ADR on cluster-scoped market evidence).
    market_evidence_tokens: dict[str, list[frozenset[str]]]


@dataclass
class ClusterContext:
    member_count: int = 0
    access_counts: dict[str, int] = field(default_factory=dict)
    platforms: set[str] = field(default_factory=set)
    compliant_platforms: set[str] = field(default_factory=set)
    interaction_likes: int = 0
    reply_count: int = 0
    content_growth: float | None = None
    text_tokens: frozenset[str] = frozenset()


class ScoringPipeline:
    """Scores every active ProblemCluster for a creator, then aggregates per creator."""

    def __init__(
        self,
        session: AsyncSession,
        rules_path: str = "rules/scoring.yaml",
    ) -> None:
        self._session = session
        self._rules = load_scoring_rules(rules_path)
        self._weights: dict[str, float] = self._rules.get("weights", {})
        self._confidence_thresholds: dict[str, Any] | None = self._rules.get(
            "confidence_thresholds",
        )

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
                run=run,
            ):
                creator_ctx = await self._load_creator_context(creator_id)
                clusters = await active_clusters_for_creator(self._session, creator_id)

                await supersede(
                    self._session, OpportunityScore,
                    OpportunityScore.creator_id == creator_id,
                )
                await supersede(
                    self._session, CreatorScore,
                    CreatorScore.creator_id == creator_id,
                )

                opp_scores: list[OpportunityScore] = []
                for cluster in clusters:
                    opp_scores.append(
                        await self._score_opportunity(cluster, creator_id, creator_ctx, run.id)
                    )
                    stats.ok()

                await self._score_creator(creator_id, opp_scores, creator_ctx, run.id)
                stats.extra["opportunities"] = len(opp_scores)
                await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Scoring pipeline failed")
            raise

        return run

    # ── Creator-level context ────────────────────────────────────────

    async def _load_creator_context(self, creator_id: str) -> CreatorContext:
        accounts = (
            await self._session.execute(
                select(CreatorPlatformAccount).where(
                    CreatorPlatformAccount.creator_id == creator_id
                )
            )
        ).scalars().all()
        subscriber_count = max((a.subscriber_count or 0 for a in accounts), default=0) or None
        audience_platforms = sorted({a.platform for a in accounts if a.platform != "web"})

        creator_runs = select(ResearchRun.id).where(ResearchRun.creator_id == creator_id)

        creator_obs = (
            await self._session.execute(
                select(ProblemObservation.text)
                .join(Evidence, Evidence.id == ProblemObservation.evidence_id)
                .where(
                    Evidence.research_run_id.in_(creator_runs),
                    ProblemObservation.source_side == "creator",
                )
            )
        ).all()
        creator_tokens = [tokens(row[0]) for row in creator_obs]

        pages = (
            await self._session.execute(
                select(ContentItem).where(
                    ContentItem.creator_id == creator_id, ContentItem.platform == "web"
                )
            )
        ).scalars().all()
        monetisation: Counter[str] = Counter()
        commerce_page_ids: list[str] = []
        for page in pages:
            kinds = set((page.extra or {}).get("commerce_signals") or [])
            for kind in kinds:
                monetisation[kind] += 1
            if kinds & COMMERCE_KINDS:
                commerce_page_ids.append(page.external_id)
        commerce_tokens: list[frozenset[str]] = []
        if commerce_page_ids:
            texts = (
                await self._session.execute(
                    select(Evidence.source_id, Evidence.raw_text).where(
                        Evidence.source_platform == "web",
                        Evidence.source_id.in_(commerce_page_ids),
                        Evidence.research_run_id.in_(creator_runs),
                    )
                )
            ).all()
            commerce_tokens = [tokens(raw) for _, raw in texts]

        niche_ids = select(CreatorNiche.niche_id).where(
            CreatorNiche.creator_id == creator_id,
        )
        niche_runs = select(ResearchRun.id).where(
            ResearchRun.niche_id.in_(niche_ids),
        )
        market_rows = (
            await self._session.execute(
                select(Evidence.evidence_type, Evidence.raw_text).where(
                    Evidence.research_run_id.in_(niche_runs),
                    Evidence.evidence_type.in_(_MARKET_EVIDENCE_TYPES),
                )
            )
        ).all()
        market_evidence_tokens: dict[str, list[frozenset[str]]] = defaultdict(list)
        for et, raw_text in market_rows:
            market_evidence_tokens[et.value].append(tokens(raw_text))

        return CreatorContext(
            subscriber_count=subscriber_count,
            audience_platforms=audience_platforms,
            creator_observation_tokens=creator_tokens,
            commerce_page_tokens=commerce_tokens,
            commerce_signal_count=sum(monetisation.values()),
            monetisation=dict(monetisation),
            engagement_rate_by_platform=await self._engagement_rates(creator_id),
            follower_growth=await self._follower_growth(accounts),
            market_evidence_tokens=dict(market_evidence_tokens),
        )

    async def _engagement_rates(self, creator_id: str) -> dict[str, float]:
        rows = (
            await self._session.execute(
                select(
                    ContentItem.platform,
                    func.sum(ContentItem.view_count),
                    func.sum(ContentItem.like_count),
                    func.sum(ContentItem.comment_count),
                )
                .where(ContentItem.creator_id == creator_id, ContentItem.platform != "web")
                .group_by(ContentItem.platform)
            )
        ).all()
        rates: dict[str, float] = {}
        for platform, views, likes, comments in rows:
            if views:
                rates[platform] = round(((likes or 0) + (comments or 0)) / views, 4)
        return rates

    async def _follower_growth(self, accounts: Any) -> float | None:
        growths: list[float] = []
        for account in accounts:
            rows = (
                await self._session.execute(
                    select(MetricsSnapshot.follower_count, MetricsSnapshot.captured_at)
                    .where(
                        MetricsSnapshot.platform_account_id == account.id,
                        MetricsSnapshot.follower_count.isnot(None),
                    )
                    .order_by(MetricsSnapshot.captured_at)
                )
            ).all()
            if len(rows) >= 2 and rows[0][1] != rows[-1][1]:
                g = growth_ratio(rows[0][0], rows[-1][0])
                if g is not None:
                    growths.append(g)
        return max(growths) if growths else None

    # ── Cluster-level context ────────────────────────────────────────

    async def _load_cluster_context(self, cluster: ProblemCluster) -> ClusterContext:
        ctx = ClusterContext()
        rows = (
            await self._session.execute(
                select(
                    ProblemObservation.text,
                    Evidence.source_id,
                    Evidence.source_platform,
                    Evidence.access_method,
                    Evidence.compliance_status,
                )
                .join(
                    ProblemClusterMember,
                    ProblemClusterMember.observation_id == ProblemObservation.id,
                )
                .join(Evidence, Evidence.id == ProblemObservation.evidence_id)
                .where(ProblemClusterMember.cluster_id == cluster.id)
            )
        ).all()
        ctx.member_count = len(rows)

        access: Counter[str] = Counter()
        source_ids: set[str] = set()
        text_parts = [cluster.label, cluster.description or ""]
        for text, source_id, platform, access_method, compliance in rows:
            access[access_method.value] += 1
            ctx.platforms.add(platform)
            if compliance != ComplianceStatus.TOS_RISK:
                ctx.compliant_platforms.add(platform)
            source_ids.add(source_id)
            text_parts.append(text)
        ctx.access_counts = dict(access)
        ctx.text_tokens = tokens(" ".join(text_parts))

        if source_ids:
            interactions = (
                await self._session.execute(
                    select(
                        AudienceInteraction.like_count,
                        AudienceInteraction.interaction_type,
                        AudienceInteraction.content_item_id,
                    ).where(AudienceInteraction.external_id.in_(source_ids))
                )
            ).all()
            content_ids: set[str] = set()
            for like_count, itype, content_id in interactions:
                ctx.interaction_likes += like_count or 0
                if itype is not None and itype.value == "reply":
                    ctx.reply_count += 1
                content_ids.add(content_id)
            ctx.content_growth = await self._content_growth(content_ids)
        return ctx

    async def _content_growth(self, content_ids: set[str]) -> float | None:
        """View growth across the cluster's content items, earliest vs latest snapshot."""
        if not content_ids:
            return None
        rows = (
            await self._session.execute(
                select(
                    MetricsSnapshot.content_item_id,
                    MetricsSnapshot.view_count,
                    MetricsSnapshot.captured_at,
                )
                .where(
                    MetricsSnapshot.content_item_id.in_(content_ids),
                    MetricsSnapshot.view_count.isnot(None),
                )
                .order_by(MetricsSnapshot.content_item_id, MetricsSnapshot.captured_at)
            )
        ).all()
        earliest: dict[str, tuple[int, object]] = {}
        latest: dict[str, tuple[int, object]] = {}
        for cid, views, at in rows:
            earliest.setdefault(cid, (views, at))
            latest[cid] = (views, at)
        measurable = [cid for cid in earliest if earliest[cid][1] != latest[cid][1]]
        if not measurable:
            return None
        return growth_ratio(
            sum(earliest[c][0] for c in measurable), sum(latest[c][0] for c in measurable)
        )

    # ── Lookups ──────────────────────────────────────────────────────

    async def _get_signal(self, cluster_id: str) -> CommercialSignal | None:
        result = await self._session.execute(
            select(CommercialSignal)
            .where(
                CommercialSignal.problem_cluster_id == cluster_id,
                CommercialSignal.superseded_at.is_(None),
            )
            .order_by(CommercialSignal.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def _get_competitor_strengths(self, cluster_id: str) -> list[Any]:
        """Load the strength of every Competitor row known for this cluster.

        Independent from the commerce-overlap signal above: this reads the
        explicitly-tracked Competitor list (populated by competitive research
        outside the automated pipeline). Empty list → the scoring function
        returns its neutral 0.5, contributing nothing to the aggregate.
        """
        result = await self._session.execute(
            select(Competitor.strength).where(Competitor.problem_cluster_id == cluster_id)
        )
        return list(result.scalars().all())

    async def _previous_frequency(self, cluster: ProblemCluster) -> int | None:
        """Frequency of the most recent superseded cluster with the same label."""
        result = await self._session.execute(
            select(ProblemCluster.frequency)
            .where(
                ProblemCluster.superseded_at.isnot(None),
                ProblemCluster.label == cluster.label,
                ProblemCluster.creator_id == cluster.creator_id,
                ProblemCluster.id != cluster.id,
            )
            .order_by(ProblemCluster.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── Scoring ──────────────────────────────────────────────────────

    async def _score_opportunity(
        self,
        cluster: ProblemCluster,
        creator_id: str,
        creator: CreatorContext,
        run_id: str,
    ) -> OpportunityScore:
        signal = await self._get_signal(cluster.id)
        ctx = await self._load_cluster_context(cluster)
        competitor_strengths = await self._get_competitor_strengths(cluster.id)

        signal_level = signal.signal_level if signal else SignalLevel.WEAK
        signal_confidence = signal.confidence if signal and signal.confidence is not None else 0.0

        matching_creator = sum(
            1
            for t in creator.creator_observation_tokens
            if jaccard(t, ctx.text_tokens) >= ALIGNMENT_THRESHOLD
        )
        commerce_overlap = (
            max(containment(ctx.text_tokens, page) for page in creator.commerce_page_tokens)
            if creator.commerce_page_tokens
            else None
        )
        platforms_with = len(ctx.platforms & set(creator.audience_platforms))

        components = {
            "audience_problem_frequency": score_audience_problem_frequency(cluster.frequency),
            "recency_trend": score_recency_trend(cluster.recency_score),
            "engagement_velocity": score_engagement_velocity(ctx.content_growth),
            "commercial_intent_strength": score_commercial_intent(signal_level, signal_confidence),
            "evidence_depth": score_evidence_depth(
                int(round(weighted_evidence_count(ctx.access_counts)))
            ),
            "creator_reach": score_creator_reach(creator.subscriber_count),
            "competition_saturation": score_competition_saturation(
                commerce_overlap, creator.commerce_signal_count
            ),
            "competitor_saturation": score_competitor_saturation(competitor_strengths),
            "creator_content_alignment": score_creator_content_alignment(matching_creator),
            "cross_platform_consistency": score_cross_platform_consistency(
                platforms_with, len(creator.audience_platforms)
            ),
            "external_demand_strength": score_external_demand_strength(
                _relevant_evidence_count(
                    ctx.text_tokens, creator.market_evidence_tokens.get(EvidenceType.TREND.value)
                ),
                _relevant_evidence_count(
                    ctx.text_tokens,
                    creator.market_evidence_tokens.get(EvidenceType.SEARCH_INTENT.value),
                ),
            ),
            "solution_saturation": score_solution_saturation(
                _relevant_evidence_count(
                    ctx.text_tokens, creator.market_evidence_tokens.get(EvidenceType.SOLUTION.value)
                ),
            ),
            "purchase_intent": score_purchase_intent(
                _relevant_evidence_count(
                    ctx.text_tokens,
                    creator.market_evidence_tokens.get(EvidenceType.TRANSACTION.value),
                ),
            ),
            "audience_dissatisfaction": score_audience_dissatisfaction(
                _relevant_evidence_count(
                    ctx.text_tokens,
                    creator.market_evidence_tokens.get(EvidenceType.DISSATISFACTION.value),
                ),
            ),
        }
        components = {k: round(v, 6) for k, v in components.items()}

        aggregate = compute_score(components, self._weights)
        computed = compute_hash(components, SCORING_RULE_VERSION)
        compliant_sources = len(ctx.compliant_platforms)
        band = compute_confidence_band(
            source_count=compliant_sources,
            evidence_depth=ctx.member_count,
            days_since_newest=_days_from_recency(cluster.recency_score),
            single_source=compliant_sources <= 1,
            thresholds=self._confidence_thresholds,
        )

        previous_frequency = await self._previous_frequency(cluster)
        diagnostics = {
            "interaction_likes": ctx.interaction_likes,
            "reply_count": ctx.reply_count,
            "source_mix": {
                "platforms": sorted(ctx.platforms),
                "compliant_platforms": sorted(ctx.compliant_platforms),
                "access_methods": ctx.access_counts,
            },
            "content_view_growth": ctx.content_growth,
            "creator_acknowledged": matching_creator > 0,
            "matching_creator_observations": matching_creator,
            "commerce_overlap": commerce_overlap,
            "frequency_previous_run": previous_frequency,
            "frequency_growth": growth_ratio(previous_frequency, cluster.frequency),
        }

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
            diagnostics=diagnostics,
        )
        self._session.add(opp)
        await self._session.flush()
        await mirror_scores(opportunity_scores=[opp])
        return opp

    async def _score_creator(
        self,
        creator_id: str,
        opp_scores: list[OpportunityScore],
        creator: CreatorContext,
        run_id: str,
    ) -> CreatorScore:
        if not opp_scores:
            components = {k: 0.0 for k in self._weights}
        else:
            agg_weights = [o.aggregate_score for o in opp_scores]
            total_agg = sum(agg_weights) or 1.0
            components = {
                dim: sum(
                    o.component_scores.get(dim, 0.0) * w
                    for o, w in zip(opp_scores, agg_weights)
                ) / total_agg
                for dim in self._weights
            }

        aggregate = compute_score(components, self._weights)
        computed = compute_hash(components, SCORING_RULE_VERSION)

        total_evidence = 0
        compliant: set[str] = set()
        for o in opp_scores:
            diag = o.diagnostics or {}
            total_evidence += sum((diag.get("source_mix") or {}).get("access_methods", {}).values())
            compliant.update((diag.get("source_mix") or {}).get("compliant_platforms", []))

        best_recency = max(
            (o.component_scores.get("recency_trend", 0.0) for o in opp_scores),
            default=0.0,
        )
        band = compute_confidence_band(
            source_count=len(compliant),
            evidence_depth=total_evidence,
            days_since_newest=_days_from_recency(best_recency),
            single_source=len(compliant) <= 1,
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
            diagnostics={
                "engagement_rate_by_platform": creator.engagement_rate_by_platform,
                "follower_growth": creator.follower_growth,
                "monetisation": creator.monetisation,
                "audience_platforms": creator.audience_platforms,
                "creator_observations": len(creator.creator_observation_tokens),
                "opportunities": len(opp_scores),
            },
        )
        self._session.add(creator_score)
        await self._session.flush()
        await mirror_scores(creator_scores=[creator_score])
        return creator_score


# clustering.py reserves an exact 0.0 recency_score for "no timestamp data at
# all", distinct from any real (however old) date, which decays exponentially
# and never reaches exactly 0.0. Feeding that sentinel through the inverse
# formula would divide by zero, so it maps to a fixed "unknown recency" age
# instead — comfortably past every confidence-band threshold, so it's still
# scored conservatively, just not confused with a specific measured age.
_UNKNOWN_RECENCY_DAYS = 3650


def _relevant_evidence_count(
    cluster_tokens: frozenset[str], evidence_tokens: list[frozenset[str]] | None
) -> int:
    """How many of a creator's market-evidence rows are actually about this
    cluster's problem, judged by token containment against the cluster's own
    text (label + description + member observations) — the same lexical-
    overlap approach already used for creator-content alignment and
    commerce overlap above. Evidence gathered for one problem (e.g. pricing)
    must not inflate the score of an unrelated one (e.g. scheduling) just
    because both belong to the same creator's niche."""
    if not evidence_tokens or not cluster_tokens:
        return 0
    return sum(
        1 for ev in evidence_tokens if containment(cluster_tokens, ev) >= ALIGNMENT_THRESHOLD
    )


def _days_from_recency(recency_score: float) -> int:
    """Invert clustering.py's exponential decay (recency = exp(-days/365))
    back to an approximate age in days."""
    if recency_score <= 0.0:
        return _UNKNOWN_RECENCY_DAYS
    if recency_score >= 1.0:
        return 0
    return round(-365.0 * math.log(recency_score))
