"""Intent classification pipeline — clusters → CommercialSignal rows."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.intent import (
    INTENT_PROMPT_VERSION,
    classify_cluster_intent,
)
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)


class IntentPipeline:
    """Classifies commercial intent for each ProblemCluster."""

    def __init__(
        self,
        provider: LLMProvider,
        session: AsyncSession,
        rules_path: str | None = None,
    ) -> None:
        self._provider = provider
        self._session = session
        self._rules_path = rules_path

    async def run(self, creator_id: str | None = None) -> ResearchRun:
        """Run intent classification for all clusters.

        Args:
            creator_id: Scope to clusters related to this creator, or None for all.
        """
        run = ResearchRun(
            creator_id=creator_id or "cross-creator",
            status="running",
            config_snapshot={
                "pipeline": "intent",
                "provider": self._provider.model_name,
            },
            prompt_versions={"intent": INTENT_PROMPT_VERSION},
            model_versions={"primary": self._provider.model_name},
        )
        self._session.add(run)
        await self._session.flush()

        try:
            clusters = await self._load_clusters()
            for cluster in clusters:
                await self._classify_cluster(cluster, run.id)

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = datetime.now(timezone.utc)
            logger.exception("Intent pipeline failed")
            raise
        finally:
            await self._session.flush()

        return run

    async def _load_clusters(self) -> list[ProblemCluster]:
        result = await self._session.execute(select(ProblemCluster))
        return list(result.scalars().all())

    async def _classify_cluster(
        self,
        cluster: ProblemCluster,
        research_run_id: str,
    ) -> None:
        texts = await self._get_representative_texts(cluster.id)
        if not texts:
            logger.warning("No representative texts for cluster %s", cluster.id)
            return

        classification = await classify_cluster_intent(
            provider=self._provider,
            label=cluster.label,
            description=cluster.description or "",
            frequency=cluster.frequency,
            evidence_strength=cluster.evidence_strength,
            representative_texts=texts,
            rules_path=self._rules_path,
        )

        evidence = Evidence(
            source_type="intent_classification",
            source_id=cluster.id,
            source_platform="gemini",
            raw_text=classification.rationale,
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
            research_run_id=research_run_id,
        )
        self._session.add(evidence)
        await self._session.flush()

        signal = CommercialSignal(
            problem_cluster_id=cluster.id,
            signal_level=classification.signal_level,
            evidence_id=evidence.id,
            rationale=classification.rationale,
            confidence=classification.confidence,
            classification_model=self._provider.model_name,
            prompt_version=INTENT_PROMPT_VERSION,
        )
        self._session.add(signal)
        await self._session.flush()

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
