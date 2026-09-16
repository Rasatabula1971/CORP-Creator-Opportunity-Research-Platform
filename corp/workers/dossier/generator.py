"""Dossier generator — renders a decision-ready HTML report for one creator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.competitive import Competitor
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.core.scoring.engine import get_score_band, load_scoring_rules

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


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

    async def generate(self, creator_id: str) -> str:
        data = await self._load_data(creator_id)
        return self._render(data)

    async def generate_data(self, creator_id: str) -> DossierData:
        return await self._load_data(creator_id)

    async def _load_data(self, creator_id: str) -> DossierData:
        creator = await self._load_creator(creator_id)
        if creator is None:
            raise ValueError(f"Creator not found: {creator_id}")

        accounts = await self._load_accounts(creator_id)
        creator_score = await self._load_creator_score(creator_id)
        opp_scores = await self._load_opportunity_scores(creator_id)

        opportunities: list[OpportunityContext] = []
        signals: list[SignalContext] = []

        for opp_score in opp_scores:
            cluster = await self._load_cluster(opp_score.problem_cluster_id)
            if cluster is None:
                continue

            signal = await self._load_signal(cluster.id)
            observations = await self._load_observations(cluster.id)
            competitors = await self._load_competitors(cluster.id)

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
            generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        )

    def _render(self, data: DossierData) -> str:
        template = self._env.get_template("dossier.html.j2")
        return template.render(
            creator=data.creator,
            platform_accounts=data.platform_accounts,
            creator_score=data.creator_score,
            score_band=data.score_band,
            weights=data.weights,
            opportunities=data.opportunities,
            signals=data.signals,
            data_coverage=data.data_coverage,
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
        latest_run_id = (
            select(ResearchRun.id)
            .where(
                ResearchRun.creator_id == creator_id,
                ResearchRun.config_snapshot["pipeline"].as_string() == "scoring",
                ResearchRun.status == "completed",
            )
            .order_by(ResearchRun.completed_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        result = await self._session.execute(
            select(OpportunityScore)
            .where(
                OpportunityScore.creator_id == creator_id,
                OpportunityScore.superseded_at.is_(None),
            )
            .order_by(OpportunityScore.aggregate_score.desc())
        )
        return list(result.scalars().all())

    async def _load_cluster(self, cluster_id: str) -> ProblemCluster | None:
        result = await self._session.execute(
            select(ProblemCluster).where(ProblemCluster.id == cluster_id)
        )
        return result.scalar_one_or_none()

    async def _load_signal(self, cluster_id: str) -> CommercialSignal | None:
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

    async def _load_observations(self, cluster_id: str) -> list[ProblemObservation]:
        result = await self._session.execute(
            select(ProblemObservation)
            .join(
                ProblemClusterMember,
                ProblemClusterMember.observation_id == ProblemObservation.id,
            )
            .where(ProblemClusterMember.cluster_id == cluster_id)
            .limit(10)
        )
        return list(result.scalars().all())

    async def _load_competitors(self, cluster_id: str) -> list[Competitor]:
        result = await self._session.execute(
            select(Competitor)
            .where(Competitor.problem_cluster_id == cluster_id)
            .order_by(Competitor.created_at.desc())
        )
        return list(result.scalars().all())

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
