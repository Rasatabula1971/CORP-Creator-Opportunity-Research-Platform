"""Intent classification pipeline — clusters → CommercialSignal rows."""

import logging

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
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.intent import (
    INTENT_PROMPT_VERSION,
    classify_cluster_intent,
)
from corp.workers.intelligence.runs import (
    DEFAULT_MAX_FAILURE_RATE,
    PipelineStats,
    active_clusters_for_creator,
    fail_run,
    finish_run,
    start_run,
    supersede,
)
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)


class IntentPipeline:
    """Classifies commercial intent for each active ProblemCluster.

    Runs inside the CLUSTERED state, so it does not move the creator's status.
    Each new classification supersedes the cluster's previous signal.
    """

    def __init__(
        self,
        provider: LLMProvider,
        session: AsyncSession,
        rules_path: str | None = None,
        max_failure_rate: float = DEFAULT_MAX_FAILURE_RATE,
    ) -> None:
        self._provider = provider
        self._session = session
        self._rules_path = rules_path
        self._max_failure_rate = max_failure_rate

    async def run(self, creator_id: str | None = None) -> ResearchRun:
        """Classify every active cluster for ``creator_id``, or all clusters when None."""
        run = await start_run(
            self._session,
            pipeline="intent",
            creator_id=creator_id,
            config={"provider": self._provider.model_name},
            prompt_versions={"intent": INTENT_PROMPT_VERSION},
            model_versions={"primary": self._provider.model_name},
        )
        stats = PipelineStats()

        try:
            clusters = await active_clusters_for_creator(self._session, creator_id)
            for cluster in clusters:
                await self._classify_cluster(cluster, run.id, stats)
            # "used" is what actually answered; a pool can change it mid-run (PDR #9).
            used = getattr(self._provider, "models_used", None)
            run.model_versions = {
                **(run.model_versions or {}),
                "used": sorted(used()) if used else [self._provider.model_name],
            }
            await finish_run(self._session, run, stats, max_failure_rate=self._max_failure_rate)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Intent pipeline failed")
            raise

        return run

    async def _classify_cluster(
        self,
        cluster: ProblemCluster,
        research_run_id: str,
        stats: PipelineStats,
    ) -> None:
        texts = await self._get_representative_texts(cluster.id)
        if not texts:
            logger.warning("No representative texts for cluster %s", cluster.id)
            stats.skip()
            return

        try:
            classification = await classify_cluster_intent(
                provider=self._provider,
                label=cluster.label,
                description=cluster.description or "",
                frequency=cluster.frequency,
                evidence_strength=cluster.evidence_strength,
                representative_texts=texts,
                rules_path=self._rules_path,
            )
        except LLMCallError as exc:
            stats.fail(exc)
            return

        evidence = Evidence(
            source_type="intent_classification",
            source_id=cluster.id,
            source_platform=self._provider.model_name,
            raw_text=classification.rationale,
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
            research_run_id=research_run_id,
        )
        self._session.add(evidence)
        await self._session.flush()

        await supersede(
            self._session, CommercialSignal, CommercialSignal.problem_cluster_id == cluster.id
        )
        self._session.add(
            CommercialSignal(
                problem_cluster_id=cluster.id,
                signal_level=classification.signal_level,
                evidence_id=evidence.id,
                rationale=classification.rationale,
                confidence=classification.confidence,
                classification_model=self._provider.model_name,
                prompt_version=INTENT_PROMPT_VERSION,
            )
        )
        stats.ok()
        await self._session.flush()

    async def _get_representative_texts(self, cluster_id: str) -> list[str]:
        result = await self._session.execute(
            select(ProblemObservation.text)
            .join(
                ProblemClusterMember,
                ProblemClusterMember.observation_id == ProblemObservation.id,
            )
            .where(ProblemClusterMember.cluster_id == cluster_id)
            .order_by(ProblemClusterMember.similarity_score.desc())
            .limit(10)
        )
        return [row[0] for row in result.all()]
