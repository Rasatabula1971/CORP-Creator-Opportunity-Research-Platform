"""Dossier generator — renders a decision-ready HTML report for one creator,
and (CORP1 Stage 5, T6) persists a decision-ready snapshot to the Dossier
table T0 created.

``generate`` / ``generate_data`` (pre-existing) compute a live,
request-scoped view — nothing is written to the database. ``generate_and_
persist`` (new) is a different operation: it builds the same underlying
data, adds product ideas (T5) and the full niche drill-down path, derives
a deterministic recommendation from the existing score bands (no new LLM
dependency), and writes a real ``Dossier`` row plus its ``DossierEvidence``
trail, superseding any prior active dossier for the same (creator, niche)
pair. The two paths intentionally share ``_load_data`` rather than
duplicating the aggregation logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import ColumnElement, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.competitive import Competitor
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.dossier import Dossier, DossierEvidence
from corp.core.models.evidence import Evidence, EvidenceType
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal
from corp.core.models.niche import Niche
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateEvidence,
    NicheCandidateStatus,
)
from corp.core.models.product_idea import ProductIdea, ProductIdeaEvidence
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.core.scoring.engine import get_score_band, load_scoring_rules
from corp.workers.intelligence.runs import supersede

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_LANGUAGE_PATTERNS = (
    "how do i",
    "how to",
    "how can i",
    "i wish",
    "i want",
    "i need",
    "why can't",
    "why doesn't",
    "is there a",
    "does anyone know",
    "looking for",
    "struggling with",
    "help with",
    "best way to",
    "alternative to",
)

# Mirrors rules/scoring.yaml's score_bands keys, in the same priority
# order get_score_band checks them -- used here to recover the band KEY
# (not its display label) for the deterministic recommendation, since
# get_score_band only returns the human-readable label string.
_SCORE_BAND_KEYS = ("exceptional", "strong", "moderate", "weak")


@dataclass
class OpportunityContext:
    cluster: ProblemCluster
    score: OpportunityScore
    signal: CommercialSignal | None
    observations: list[ProblemObservation]
    competitors: list[Competitor] = field(default_factory=list)


@dataclass
class SignalContext:
    cluster_label: str
    signal: CommercialSignal


@dataclass
class DataCoverage:
    source_count: int = 0
    evidence_count: int = 0
    cluster_count: int = 0
    observation_count: int = 0
    competitor_count: int = 0


@dataclass
class DossierData:
    creator: Creator
    platform_accounts: list[CreatorPlatformAccount] = field(default_factory=list)
    creator_score: CreatorScore | None = None
    score_band: str = ""
    weights: dict[str, float] = field(default_factory=dict)
    opportunities: list[OpportunityContext] = field(default_factory=list)
    signals: list[SignalContext] = field(default_factory=list)
    data_coverage: DataCoverage = field(default_factory=DataCoverage)
    generated_at: str = ""


class DossierGenerator:
    """Loads all data for a creator and renders the CORP §13 dossier."""

    def __init__(
        self,
        session: AsyncSession,
        rules_path: str = "rules/scoring.yaml",
        template_dir: Path | None = None,
    ) -> None:
        self._session = session
        self._rules = load_scoring_rules(rules_path)
        self._weights: dict[str, float] = self._rules.get("weights", {})
        tpl_dir = template_dir or _TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(tpl_dir)),
            autoescape=True,
        )

    async def generate(self, creator_id: str, niche_id: str | None = None) -> str:
        """Live HTML view. Carries the same enriched sections the persisted
        dossier does (audience analysis, demand validation, product ideas,
        recommendation) so the two never diverge.

        Scope (R10): with ``niche_id`` -- or when the creator is linked to
        exactly one niche -- evidence and the recommendation's top
        opportunity are scoped to that niche, exactly as the persisted
        dossier is. Only a multi-niche creator viewed without ``niche_id``
        falls back to the union of every linked niche and the global top."""
        data = await self._load_data(creator_id)
        linked = list(
            (
                await self._session.execute(
                    select(CreatorNiche.niche_id).where(CreatorNiche.creator_id == creator_id)
                )
            ).scalars().all()
        )
        if niche_id is None and len(linked) == 1:
            niche_id = linked[0]
        niche_ids = [niche_id] if niche_id else linked
        dossier_niche = await self._session.get(Niche, niche_id) if niche_id else None

        top = data.opportunities[0] if data.opportunities else None
        if niche_id and data.opportunities:
            niche_opps = await self._filter_niche_opportunities(data.opportunities, niche_id)
            if niche_opps:
                top = niche_opps[0]
        product_ideas = await self._load_product_ideas(creator_id)
        cluster_competitors = {o.cluster.id: o.competitors for o in data.opportunities}
        return self._render(
            data,
            audience_analysis=self._build_audience_analysis(data.opportunities),
            demand_validation=await self._build_demand_validation(creator_id, niche_ids),
            product_ideas=product_ideas,
            comparable_products={
                p.id: _comparable_products(cluster_competitors.get(p.problem_cluster_id, []))
                for p in product_ideas
            },
            recommendation=self._build_recommendation(data, top) if top else None,
            dossier_niche=dossier_niche,
        )

    async def generate_data(self, creator_id: str) -> DossierData:
        return await self._load_data(creator_id)

    async def generate_and_persist(self, creator_id: str, niche_id: str) -> Dossier:
        """Build the same aggregate view generate_data() does, enrich it
        with product ideas (T5) and the niche drill-down path, derive a
        deterministic recommendation, and persist a real Dossier row plus
        its DossierEvidence trail -- CORP1 Stage 5, T6. Supersedes any
        prior active dossier for this (creator, niche) pair; nothing is
        ever deleted."""
        data = await self._load_data(creator_id)
        if not data.opportunities:
            raise ValueError(
                f"Creator {creator_id} has no active opportunity scores to build a dossier from"
            )

        niche = await self._session.get(Niche, niche_id)
        if niche is None:
            raise ValueError(f"Niche not found: {niche_id}")

        product_ideas = await self._load_product_ideas(creator_id)
        path = await self._niche_path(niche_id)

        cluster_competitors = {
            o.cluster.id: o.competitors for o in data.opportunities
        }

        niche_opps = await self._filter_niche_opportunities(data.opportunities, niche_id)
        if not niche_opps:
            logger.warning(
                "No niche-specific opportunities for niche %s / creator %s; using global top",
                niche_id,
                creator_id,
            )
        top = niche_opps[0] if niche_opps else data.opportunities[0]
        recommendation = self._build_recommendation(data, top)

        content: dict[str, Any] = {
            "creator": {
                "id": data.creator.id,
                "name": data.creator.name,
                "niche": data.creator.niche,
                "status": data.creator.status.value,
            },
            "platform_accounts": [
                {
                    "platform": a.platform,
                    "handle": a.handle,
                    "subscriber_count": a.subscriber_count,
                    "total_view_count": a.total_view_count,
                    "video_count": a.video_count,
                    "joined_at": a.joined_at.isoformat() if a.joined_at else None,
                    "country": a.country,
                    "description": a.description,
                }
                for a in data.platform_accounts
            ],
            "creator_score": (
                {
                    "aggregate_score": data.creator_score.aggregate_score,
                    "confidence_band": data.creator_score.confidence_band.value,
                    "component_scores": data.creator_score.component_scores,
                    "diagnostics": data.creator_score.diagnostics,
                }
                if data.creator_score
                else None
            ),
            "score_band": data.score_band,
            "opportunities": [
                {
                    "cluster_label": o.cluster.label,
                    "cluster_description": o.cluster.description,
                    "aggregate_score": o.score.aggregate_score,
                    "confidence_band": o.score.confidence_band.value,
                    "component_scores": o.score.component_scores,
                    "signal_level": o.signal.signal_level.value if o.signal else None,
                    "observation_count": len(o.observations),
                    "sample_evidence": [obs.text[:500] for obs in o.observations[:3]],
                    "frequency": o.cluster.frequency,
                    "recency_score": o.cluster.recency_score,
                    "evidence_strength": o.cluster.evidence_strength,
                    "competitor_count": len(o.competitors),
                    "competitors": [
                        {
                            "name": c.name,
                            "competitor_type": c.competitor_type.value,
                            "strength": c.strength.value,
                            "gap_notes": c.gap_notes,
                            "url": c.url,
                        }
                        for c in o.competitors
                    ],
                }
                for o in data.opportunities
            ],
            "product_ideas": [
                {
                    "id": p.id,
                    "title": p.title,
                    "description": p.description,
                    "idea_type": p.idea_type.value,
                    "complexity": p.complexity.value,
                    "price_min": p.price_min,
                    "price_max": p.price_max,
                    "fit_rationale": p.fit_rationale,
                    "evidence_terms": p.evidence_terms,
                    "comparable_products": _comparable_products(
                        cluster_competitors.get(p.problem_cluster_id, [])
                    ),
                }
                for p in product_ideas
            ],
            "data_coverage": {
                "source_count": data.data_coverage.source_count,
                "evidence_count": data.data_coverage.evidence_count,
                "cluster_count": data.data_coverage.cluster_count,
                "observation_count": data.data_coverage.observation_count,
                "competitor_count": data.data_coverage.competitor_count,
            },
            "audience_analysis": self._build_audience_analysis(data.opportunities),
            "demand_validation": await self._build_demand_validation(creator_id, [niche_id]),
            "niche_path": path,
            "recommendation": recommendation,
            "generated_at": data.generated_at,
        }

        superseded = await supersede(
            self._session,
            Dossier,
            Dossier.creator_id == creator_id,
            Dossier.niche_id == niche_id,
        )
        logger.info(
            "Superseded %d prior dossier(s) for creator %s / niche %s",
            superseded, creator_id, niche_id,
        )

        dossier = Dossier(
            creator_id=creator_id,
            niche_id=niche_id,
            opportunity_score_id=top.score.id,
            research_run_id=top.score.research_run_id,
            content=content,
            niche_path=path,
        )
        self._session.add(dossier)
        await self._session.flush()

        for evidence_id in await self._collect_evidence_ids(data.opportunities, product_ideas):
            self._session.add(DossierEvidence(dossier_id=dossier.id, evidence_id=evidence_id))
        await self._session.flush()

        return dossier

    async def _load_data(self, creator_id: str) -> DossierData:
        creator = await self._load_creator(creator_id)
        if creator is None:
            raise ValueError(f"Creator not found: {creator_id}")

        accounts = await self._load_accounts(creator_id)
        creator_score = await self._load_creator_score(creator_id)
        opp_scores = await self._load_opportunity_scores(creator_id)

        cluster_ids = [s.problem_cluster_id for s in opp_scores]
        clusters_by_id = await self._load_clusters_batch(cluster_ids)
        signals_by_cluster = await self._load_signals_batch(cluster_ids)
        observations_by_cluster = await self._load_observations_batch(cluster_ids)
        competitors_by_cluster = await self._load_competitors_batch(cluster_ids)

        opportunities: list[OpportunityContext] = []
        signals: list[SignalContext] = []

        for opp_score in opp_scores:
            cluster = clusters_by_id.get(opp_score.problem_cluster_id)
            if cluster is None:
                continue

            signal = signals_by_cluster.get(cluster.id)
            observations = observations_by_cluster.get(cluster.id, [])
            competitors = competitors_by_cluster.get(cluster.id, [])

            opportunities.append(OpportunityContext(
                cluster=cluster,
                score=opp_score,
                signal=signal,
                observations=observations,
                competitors=competitors,
            ))

            if signal:
                signals.append(SignalContext(
                    cluster_label=cluster.label,
                    signal=signal,
                ))

        opportunities.sort(key=lambda o: o.score.aggregate_score, reverse=True)

        score_band = ""
        if creator_score:
            score_band = get_score_band(creator_score.aggregate_score, self._rules)

        coverage = await self._compute_coverage(creator_id, opportunities)

        return DossierData(
            creator=creator,
            platform_accounts=accounts,
            creator_score=creator_score,
            score_band=score_band,
            weights=self._weights,
            opportunities=opportunities,
            signals=signals,
            data_coverage=coverage,
            generated_at=datetime.now(UTC).isoformat(),
        )

    def _render(
        self,
        data: DossierData,
        *,
        audience_analysis: dict[str, Any] | None = None,
        demand_validation: dict[str, Any] | None = None,
        product_ideas: list[ProductIdea] | None = None,
        comparable_products: dict[str, list[dict[str, Any]]] | None = None,
        recommendation: dict[str, Any] | None = None,
        dossier_niche: Niche | None = None,
    ) -> str:
        template = self._env.get_template("dossier.html.j2")
        return template.render(
            dossier_niche=dossier_niche,
            creator=data.creator,
            platform_accounts=data.platform_accounts,
            creator_score=data.creator_score,
            score_band=data.score_band,
            weights=data.weights,
            opportunities=data.opportunities,
            signals=data.signals,
            data_coverage=data.data_coverage,
            audience_analysis=audience_analysis,
            demand_validation=demand_validation,
            product_ideas=product_ideas or [],
            comparable_products=comparable_products or {},
            recommendation=recommendation,
            generated_at=data.generated_at,
        )

    async def _load_creator(self, creator_id: str) -> Creator | None:
        result = await self._session.execute(
            select(Creator).where(Creator.id == creator_id)
        )
        return result.scalar_one_or_none()

    async def _load_accounts(self, creator_id: str) -> list[CreatorPlatformAccount]:
        result = await self._session.execute(
            select(CreatorPlatformAccount).where(
                CreatorPlatformAccount.creator_id == creator_id
            )
        )
        return list(result.scalars().all())

    async def _load_creator_score(self, creator_id: str) -> CreatorScore | None:
        result = await self._session.execute(
            select(CreatorScore)
            .where(
                CreatorScore.creator_id == creator_id,
                CreatorScore.superseded_at.is_(None),
            )
            .order_by(CreatorScore.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _load_opportunity_scores(self, creator_id: str) -> list[OpportunityScore]:
        # Active-row filtering via superseded_at is the run-scoping mechanism:
        # every new scoring run supersedes the previous run's rows, so the
        # non-superseded set IS the latest completed run's output.
        result = await self._session.execute(
            select(OpportunityScore)
            .where(
                OpportunityScore.creator_id == creator_id,
                OpportunityScore.superseded_at.is_(None),
            )
            .order_by(OpportunityScore.aggregate_score.desc())
        )
        return list(result.scalars().all())

    async def _load_clusters_batch(
        self, cluster_ids: list[str],
    ) -> dict[str, ProblemCluster]:
        if not cluster_ids:
            return {}
        result = await self._session.execute(
            select(ProblemCluster).where(ProblemCluster.id.in_(cluster_ids))
        )
        return {c.id: c for c in result.scalars().all()}

    async def _load_signals_batch(
        self, cluster_ids: list[str],
    ) -> dict[str, CommercialSignal]:
        if not cluster_ids:
            return {}
        result = await self._session.execute(
            select(CommercialSignal)
            .where(
                CommercialSignal.problem_cluster_id.in_(cluster_ids),
                CommercialSignal.superseded_at.is_(None),
            )
            .order_by(CommercialSignal.created_at.desc())
        )
        lookup: dict[str, CommercialSignal] = {}
        for sig in result.scalars().all():
            lookup.setdefault(sig.problem_cluster_id, sig)
        return lookup

    async def _load_observations_batch(
        self, cluster_ids: list[str],
    ) -> dict[str, list[ProblemObservation]]:
        if not cluster_ids:
            return {}
        result = await self._session.execute(
            select(ProblemObservation, ProblemClusterMember.cluster_id)
            .join(
                ProblemClusterMember,
                ProblemClusterMember.observation_id == ProblemObservation.id,
            )
            .where(ProblemClusterMember.cluster_id.in_(cluster_ids))
            .order_by(
                ProblemClusterMember.cluster_id,
                ProblemObservation.confidence.desc().nullslast(),
                ProblemObservation.id,
            )
        )
        lookup: dict[str, list[ProblemObservation]] = {}
        for obs, cid in result.all():
            bucket = lookup.setdefault(cid, [])
            if len(bucket) < 10:
                bucket.append(obs)
        return lookup

    async def _load_competitors_batch(
        self, cluster_ids: list[str],
    ) -> dict[str, list[Competitor]]:
        if not cluster_ids:
            return {}
        result = await self._session.execute(
            select(Competitor)
            .where(Competitor.problem_cluster_id.in_(cluster_ids))
            .order_by(Competitor.created_at.desc())
        )
        lookup: dict[str, list[Competitor]] = {}
        for comp in result.scalars().all():
            bucket = lookup.setdefault(comp.problem_cluster_id, [])
            if len(bucket) < 20:
                bucket.append(comp)
        return lookup

    async def _compute_coverage(
        self,
        creator_id: str,
        opportunities: list[OpportunityContext],
    ) -> DataCoverage:
        src_result = await self._session.execute(
            select(func.count(func.distinct(CreatorPlatformAccount.platform))).where(
                CreatorPlatformAccount.creator_id == creator_id
            )
        )
        source_count = src_result.scalar() or 0

        creator_runs = select(ResearchRun.id).where(ResearchRun.creator_id == creator_id)
        ev_result = await self._session.execute(
            select(func.count())
            .select_from(Evidence)
            .where(Evidence.research_run_id.in_(creator_runs))
        )
        evidence_count = ev_result.scalar() or 0

        obs_count = sum(len(o.observations) for o in opportunities)
        comp_count = sum(len(o.competitors) for o in opportunities)

        return DataCoverage(
            source_count=source_count,
            evidence_count=evidence_count,
            cluster_count=len(opportunities),
            observation_count=obs_count,
            competitor_count=comp_count,
        )

    # ── T6: persistence helpers ──────────────────────────────────────

    @staticmethod
    def _build_audience_analysis(
        opportunities: list[OpportunityContext],
    ) -> dict[str, Any]:
        top_questions: list[dict[str, Any]] = []
        all_audience_obs: list[ProblemObservation] = []

        for opp in opportunities:
            audience_obs = [o for o in opp.observations if o.source_side == "audience"]
            all_audience_obs.extend(audience_obs)
            if audience_obs:
                top_questions.append({
                    "cluster_label": opp.cluster.label,
                    "questions": [
                        {"text": o.text[:500], "sentiment": o.sentiment, "urgency": o.urgency}
                        for o in audience_obs[:5]
                    ],
                })

        themes = [
            {
                "label": opp.cluster.label,
                "description": opp.cluster.description,
                "frequency": opp.cluster.frequency,
                "observation_count": len(opp.observations),
                "evidence_strength": opp.cluster.evidence_strength,
                "recency_score": opp.cluster.recency_score,
            }
            for opp in opportunities
        ]

        pattern_counts: dict[str, int] = {}
        for obs in all_audience_obs:
            lower = obs.text.lower()
            for pat in _LANGUAGE_PATTERNS:
                if lower.startswith(pat) or f" {pat} " in lower:
                    pattern_counts[pat] = pattern_counts.get(pat, 0) + 1
        language_patterns = [
            {"pattern": p, "count": c}
            for p, c in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        sentiment_dist: dict[str, int] = {}
        urgency_dist: dict[str, int] = {}
        for obs in all_audience_obs:
            if obs.sentiment:
                sentiment_dist[obs.sentiment] = sentiment_dist.get(obs.sentiment, 0) + 1
            if obs.urgency:
                urgency_dist[obs.urgency] = urgency_dist.get(obs.urgency, 0) + 1

        return {
            "top_questions": top_questions,
            "recurring_themes": themes,
            "language_patterns": language_patterns,
            "engagement_quality": {
                "total_audience_observations": len(all_audience_obs),
                "sentiment_distribution": sentiment_dist,
                "urgency_distribution": urgency_dist,
            },
        }

    @staticmethod
    def _niche_evidence_clause(niche_ids: list[str]) -> ColumnElement[bool]:
        """Evidence that belongs to any of ``niche_ids``. Two sources, because the niche
        pipeline links evidence differently at each stage: the depth-0 drill
        (T3) records evidence on the NicheCandidate that later became the
        niche (PROMOTED) or was folded into it (MERGED), while research_more
        and creator onboarding tag their ResearchRun with niche_id directly.
        Creator-level research runs carry no niche_id at all, so a
        creator-only scope misses every TREND/TRANSACTION/MONETISATION row."""
        if not niche_ids:
            return false()
        niche_runs = select(ResearchRun.id).where(ResearchRun.niche_id.in_(niche_ids))
        candidate_evidence = (
            select(NicheCandidateEvidence.evidence_id)
            .join(NicheCandidate, NicheCandidate.id == NicheCandidateEvidence.candidate_id)
            .where(
                NicheCandidate.niche_id.in_(niche_ids),
                NicheCandidate.status.in_(
                    [NicheCandidateStatus.PROMOTED, NicheCandidateStatus.MERGED]
                ),
            )
        )
        return or_(
            Evidence.research_run_id.in_(niche_runs),
            Evidence.id.in_(candidate_evidence),
        )

    async def count_new_evidence(
        self, creator_id: str, niche_ids: list[str], since: datetime
    ) -> int:
        """Distinct evidence rows in this creator/niche scope collected after
        ``since`` -- the "more people are saying this" half of R12's
        resurface rule. Same scope as demand validation."""
        creator_runs = select(ResearchRun.id).where(ResearchRun.creator_id == creator_id)
        result = await self._session.execute(
            select(func.count(func.distinct(Evidence.id))).where(
                or_(
                    Evidence.research_run_id.in_(creator_runs),
                    self._niche_evidence_clause(niche_ids),
                ),
                Evidence.collected_at > since,
            )
        )
        return int(result.scalar() or 0)

    async def _build_demand_validation(
        self, creator_id: str, niche_ids: list[str],
    ) -> dict[str, Any]:
        creator_runs = select(ResearchRun.id).where(
            ResearchRun.creator_id == creator_id
        )
        in_scope = or_(
            Evidence.research_run_id.in_(creator_runs),
            self._niche_evidence_clause(niche_ids),
        )

        type_result = await self._session.execute(
            select(Evidence.evidence_type, func.count())
            .where(in_scope)
            .group_by(Evidence.evidence_type)
        )
        by_type: dict[str, int] = {}
        for ev_type, count in type_result.all():
            if isinstance(ev_type, EvidenceType):
                by_type[ev_type.value] = count

        platform_result = await self._session.execute(
            select(Evidence.source_platform, func.count())
            .where(in_scope)
            .group_by(Evidence.source_platform)
        )
        by_platform: dict[str, int] = {
            row[0]: row[1] for row in platform_result.all()
        }

        return {
            "evidence_by_type": by_type,
            "evidence_by_platform": by_platform,
            "signals": {
                "search_intent": by_type.get("search_intent", 0),
                "trend": by_type.get("trend", 0),
                "planning_intent": by_type.get("planning_intent", 0),
                "transaction": by_type.get("transaction", 0),
                "monetisation": by_type.get("monetisation", 0),
                "dissatisfaction": by_type.get("dissatisfaction", 0),
            },
            # Keys are the source_platform strings the adapters emit
            # (registry.KNOWN_PLATFORMS): Kickstarter+Indiegogo share
            # "crowdfunding", Patreon+Substack share "patreon_substack",
            # Gumroad/Etsy/Udemy share "marketplace".
            "platform_highlights": {
                "reddit_discussions": by_platform.get("reddit", 0),
                "search_demand": by_platform.get("searchdemand", 0),
                "google_trends": by_platform.get("googletrends", 0),
                # No Pinterest adapter yet (T11 parked); stays 0 until it lands.
                "pinterest_activity": by_platform.get("pinterest", 0),
                "crowdfunding_signals": by_platform.get("crowdfunding", 0),
                "patreon_substack_indicators": by_platform.get("patreon_substack", 0),
                "marketplace_competition": by_platform.get("marketplace", 0),
                "amazon_reviews": by_platform.get("amazon_reviews", 0),
                "app_store_reviews": by_platform.get("appstore", 0),
            },
        }

    async def _filter_niche_opportunities(
        self, opportunities: list[OpportunityContext], niche_id: str
    ) -> list[OpportunityContext]:
        """Return only opportunities whose evidence belongs to this niche
        (see _niche_evidence_clause), preserving the existing sort order.
        Falls back to empty if no evidence links exist (caller picks global
        top)."""
        all_ev_ids = {obs.evidence_id for o in opportunities for obs in o.observations}
        if not all_ev_ids:
            return []
        result = await self._session.execute(
            select(Evidence.id).where(
                Evidence.id.in_(all_ev_ids), self._niche_evidence_clause([niche_id])
            )
        )
        niche_ev_ids = set(result.scalars().all())
        if not niche_ev_ids:
            return []
        return [
            o for o in opportunities
            if any(obs.evidence_id in niche_ev_ids for obs in o.observations)
        ]

    async def _load_product_ideas(self, creator_id: str) -> list[ProductIdea]:
        result = await self._session.execute(
            select(ProductIdea)
            .where(ProductIdea.creator_id == creator_id, ProductIdea.superseded_at.is_(None))
            .order_by(ProductIdea.created_at.desc())
        )
        return list(result.scalars().all())

    async def _niche_path(self, niche_id: str) -> list[dict[str, Any]]:
        """Walk Niche.parent_niche_id from ``niche_id`` up to the root.
        Returns root-to-leaf order. A cycle (should never happen, but the
        column has no DB-level acyclicity guarantee) stops the walk rather
        than looping forever."""
        path: list[dict[str, Any]] = []
        current_id: str | None = niche_id
        seen: set[str] = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            niche = await self._session.get(Niche, current_id)
            if niche is None:
                break
            path.append(
                {"id": niche.id, "canonical_name": niche.canonical_name, "depth": niche.depth}
            )
            current_id = niche.parent_niche_id
        path.reverse()
        return path

    def _build_recommendation(
        self, data: DossierData, top: OpportunityContext
    ) -> dict[str, Any]:
        """Deterministic, rule-based -- no new LLM dependency. Mirrors the
        human decision gate's own vocabulary (Reject / Research More /
        Watch / Approve) so the suggestion reads as a same-language nudge,
        never a binding decision; the human gate remains the actual
        decision-maker (Stage 3's Automation Matrix)."""
        band_key = _score_band_key(top.score.aggregate_score, self._rules)
        confidence = top.score.confidence_band.value

        if confidence == "insufficient":
            action = "research_more"
        elif band_key in ("exceptional", "strong") and confidence in ("high", "medium"):
            action = "approve"
        elif band_key == "weak":
            action = "reject"
        else:
            action = "watch"

        risks: list[str] = []
        if data.data_coverage.source_count < 2:
            risks.append("Evidence comes from a single platform only.")
        if data.data_coverage.competitor_count == 0:
            risks.append("No competitive landscape data collected yet.")
        if top.signal is None:
            risks.append("No direct commercial-intent signal found for the top opportunity.")

        next_steps: list[str] = []
        if action == "research_more":
            next_steps.append("Collect more evidence before deciding.")
        elif action == "approve":
            next_steps.append("Proceed to partnership outreach (CORP2).")
        elif action == "watch":
            next_steps.append("Re-score after the next research pass.")
        else:
            next_steps.append("Reject and move to the next candidate opportunity.")

        return {
            "suggested_action": action,
            "confidence": confidence,
            "rationale": (
                f"{data.score_band}; top opportunity {top.cluster.label!r} scored "
                f"{top.score.aggregate_score:.2f} ({confidence} confidence) from "
                f"{data.data_coverage.observation_count} observations across "
                f"{data.data_coverage.source_count} source(s)."
            ),
            "risks": risks,
            "next_steps": next_steps,
        }

    async def _collect_evidence_ids(
        self, opportunities: list[OpportunityContext], product_ideas: list[ProductIdea]
    ) -> list[str]:
        """Every evidence row backing the dossier's opportunities and
        product ideas, filtered to rows traceable to a real ResearchRun
        (Stage 4 acceptance test) -- a row with no research_run_id is
        never linked into a persisted dossier's evidence trail."""
        ids: set[str] = set()
        for opp in opportunities:
            for obs in opp.observations:
                ids.add(obs.evidence_id)
        for idea in product_ideas:
            result = await self._session.execute(
                select(ProductIdeaEvidence.evidence_id).where(
                    ProductIdeaEvidence.product_idea_id == idea.id
                )
            )
            ids.update(result.scalars().all())

        if not ids:
            return []
        result = await self._session.execute(
            select(Evidence.id).where(
                Evidence.id.in_(ids), Evidence.research_run_id.isnot(None)
            )
        )
        return list(result.scalars().all())


def _comparable_products(competitors: list[Competitor]) -> list[dict[str, Any]]:
    """The spec's "comparable products" for a product idea: the competitors
    already recorded against the idea's cluster. One mapping shared by the
    persisted content and the HTML view."""
    return [
        {"name": c.name, "url": c.url, "strength": c.strength.value}
        for c in competitors[:5]
    ]


def _score_band_key(aggregate: float, rules: dict[str, Any]) -> str:
    """Same lookup as corp.core.scoring.engine.get_score_band, but returns
    the band KEY ("exceptional") rather than its display label ("Exceptional
    opportunity") -- the label is free-text from YAML and not safe to
    branch logic on."""
    bands = rules.get("score_bands", {})
    for band_key in _SCORE_BAND_KEYS:
        band = bands.get(band_key)
        if not band or "min" not in band:
            continue
        if aggregate >= band["min"]:
            return band_key
    return "weak"
