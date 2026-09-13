"""Competitive discovery pipeline — clusters + descriptions → Competitor rows."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.competitive import Competitor, CompetitorStrength, CompetitorType
from corp.core.models.content import ContentItem
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.workflow import ResearchRun
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

COMPETITIVE_PROMPT_VERSION = "competitive_v1"

_SYSTEM_PROMPT = (
    "You are a competitive intelligence analyst. Given an audience problem cluster "
    "and related video descriptions, identify existing products, services, tools, "
    "creators, or DIY workarounds that the audience currently uses to address this problem."
)

_DISCOVERY_TEMPLATE = """\
Analyze the following problem cluster and related content to identify competitors — \
existing solutions the audience mentions, uses, or could use.

Problem cluster: "{label}"
Cluster description: "{description}"
Frequency: {frequency} audience mentions

Representative audience comments:
{comments}

Related video descriptions (may mention products, sponsors, affiliates):
{descriptions}

Identify competitors/alternatives for this problem. For each:
- "name": Product, service, tool, or creator name (1-5 words)
- "competitor_type": "direct" (same solution), "substitute" (different approach to same problem), \
or "diy_workaround" (manual/free approach)
- "strength": "weak" (rarely mentioned, niche), "moderate" (known option, some traction), \
or "strong" (dominant, frequently referenced)
- "url": URL if mentioned or well-known, otherwise null
- "gap_notes": 1-2 sentences on what gap remains — why the audience still has this problem \
despite this competitor existing

Return JSON: {{"competitors": [...]}}
If no competitors are identifiable, return {{"competitors": []}}.
"""

_STRENGTH_MAP = {
    "weak": CompetitorStrength.WEAK,
    "moderate": CompetitorStrength.MODERATE,
    "strong": CompetitorStrength.STRONG,
}

_TYPE_MAP = {
    "direct": CompetitorType.DIRECT,
    "substitute": CompetitorType.SUBSTITUTE,
    "diy_workaround": CompetitorType.DIY_WORKAROUND,
}


class CompetitivePipeline:
    """Discovers competitors for each ProblemCluster via LLM analysis."""

    def __init__(
        self,
        provider: LLMProvider,
        session: AsyncSession,
    ) -> None:
        self._provider = provider
        self._session = session

    async def run(self, creator_id: str) -> ResearchRun:
        """Run competitive discovery for all clusters belonging to a creator."""
        run = ResearchRun(
            creator_id=creator_id,
            status="running",
            started_at=datetime.now(timezone.utc),
            config_snapshot={
                "pipeline": "competitive",
                "provider": self._provider.model_name,
            },
            prompt_versions={"competitive": COMPETITIVE_PROMPT_VERSION},
            model_versions={"primary": self._provider.model_name},
        )
        self._session.add(run)
        await self._session.flush()

        try:
            clusters = await self._load_clusters(creator_id)
            descriptions = await self._load_descriptions(creator_id)

            for cluster in clusters:
                await self._discover_competitors(cluster, descriptions, run.id)

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = datetime.now(timezone.utc)
            logger.exception("Competitive pipeline failed for creator %s", creator_id)
            raise
        finally:
            await self._session.flush()

        return run

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

    async def _load_descriptions(self, creator_id: str) -> list[str]:
        result = await self._session.execute(
            select(ContentItem.description)
            .where(
                ContentItem.creator_id == creator_id,
                ContentItem.description.isnot(None),
            )
            .limit(20)
        )
        return [row[0] for row in result.all() if row[0]]

    async def _get_representative_texts(self, cluster_id: str) -> list[str]:
        result = await self._session.execute(
            select(ProblemObservation.text)
            .join(
                ProblemClusterMember,
                ProblemClusterMember.observation_id == ProblemObservation.id,
            )
            .where(ProblemClusterMember.cluster_id == cluster_id)
            .limit(10)
        )
        return [row[0] for row in result.all()]

    async def _discover_competitors(
        self,
        cluster: ProblemCluster,
        descriptions: list[str],
        research_run_id: str,
    ) -> None:
        texts = await self._get_representative_texts(cluster.id)
        if not texts:
            return

        comments_str = "\n".join(f"- {t[:300]}" for t in texts[:10])
        desc_str = "\n".join(
            f"- {d[:400]}" for d in descriptions[:5]
        ) or "(no descriptions available)"

        prompt = _DISCOVERY_TEMPLATE.format(
            label=cluster.label,
            description=(cluster.description or "")[:500],
            frequency=cluster.frequency,
            comments=comments_str,
            descriptions=desc_str,
        )

        try:
            result = await self._provider.generate_json(prompt, system=_SYSTEM_PROMPT)
        except Exception:
            logger.exception(
                "Competitive discovery failed for cluster %s (%s)",
                cluster.id, cluster.label,
            )
            return

        raw_competitors = result.get("competitors", [])
        if not raw_competitors:
            return

        evidence = Evidence(
            source_type="competitive_analysis",
            source_id=cluster.id,
            source_platform=self._provider.model_name,
            raw_text=f"Competitive analysis for cluster: {cluster.label}",
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
            research_run_id=research_run_id,
        )
        self._session.add(evidence)
        await self._session.flush()

        seen_names: set[str] = set()
        for item in raw_competitors:
            if not isinstance(item, dict) or not item.get("name"):
                continue

            name = str(item["name"])[:255]
            name_lower = name.lower()
            if name_lower in seen_names:
                continue
            seen_names.add(name_lower)

            type_str = str(item.get("competitor_type", "direct")).lower()
            strength_str = str(item.get("strength", "moderate")).lower()

            competitor = Competitor(
                problem_cluster_id=cluster.id,
                name=name,
                competitor_type=_TYPE_MAP.get(type_str, CompetitorType.DIRECT),
                strength=_STRENGTH_MAP.get(strength_str, CompetitorStrength.MODERATE),
                url=str(item["url"])[:500] if item.get("url") else None,
                gap_notes=str(item.get("gap_notes", ""))[:1000] or None,
                evidence_id=evidence.id,
            )
            self._session.add(competitor)

        await self._session.flush()
        logger.info(
            "Discovered %d competitors for cluster %s (%s)",
            len(seen_names), cluster.id, cluster.label,
        )
