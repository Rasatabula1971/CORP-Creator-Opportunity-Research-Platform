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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.competitive import Competitor
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.dossier import Dossier, DossierEvidence
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal
from corp.core.models.niche import Niche
from corp.core.models.product_idea import ProductIdea, ProductIdeaEvidence
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.core.scoring.engine import get_score_band, load_scoring_rules
from corp.workers.intelligence.runs import supersede

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

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

    async def generate(self, creator_id: str) -> str:
        data = await self._load_data(creator_id)
        return self._render(data)

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

        niche_opps = await self._filter_niche_opportunities(data.opportunities, niche_id)
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
                }
                for a in data.platform_accounts
            ],
            "creator_score": (
                {
                    "aggregate_score": data.creator_score.aggregate_score,
                    "confidence_band": data.creator_score.confidence_band.value,
                }
                if data.creator_score
                else None
            ),
            "score_band": data.score_band,
            "opportunities": [
                {
                    "cluster_label": o.cluster.label,
                    "aggregate_score": o.score.aggregate_score,
                    "confidence_band": o.score.confidence_band.value,
                    "component_scores": o.score.component_scores,
                    "signal_level": o.signal.signal_level.value if o.signal else None,
                    "observation_count": len(o.observations),
                    "competitor_count": len(o.competitors),
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
            .order_by(ProblemObservation.confidence.desc().nullslast(), ProblemObservation.id)
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

    # ── T6: persistence helpers ──────────────────────────────────────

    async def _filter_niche_opportunities(
        self, opportunities: list[OpportunityContext], niche_id: str
    ) -> list[OpportunityContext]:
        """Return only opportunities whose evidence traces to research runs
        for this niche, preserving the existing sort order. Falls back to
        empty if no evidence links exist (caller picks global top)."""
        all_ev_ids = {obs.evidence_id for o in opportunities for obs in o.observations}
        if not all_ev_ids:
            return []
        result = await self._session.execute(
            select(Evidence.id)
            .join(ResearchRun, ResearchRun.id == Evidence.research_run_id)
            .where(Evidence.id.in_(all_ev_ids), ResearchRun.niche_id == niche_id)
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
