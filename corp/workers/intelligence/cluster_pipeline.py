"""Clustering pipeline — embed observations, cluster, persist to DB."""

import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.clustering import (
    ClusteringConfig,
    ClusterResult,
    cluster_observations,
)
from corp.workers.intelligence.embeddings import EMBEDDING_DIM, Embedder, embed_texts

logger = logging.getLogger(__name__)


class ClusterPipeline:
    """Embeds ProblemObservations, clusters them, and persists results."""

    def __init__(
        self,
        embedder: Embedder,
        session: AsyncSession,
        config: ClusteringConfig | None = None,
    ) -> None:
        self._embedder = embedder
        self._session = session
        self._config = config or ClusteringConfig()

    async def run(
        self,
        creator_id: str | None = None,
    ) -> ResearchRun:
        """Run clustering pipeline.

        Args:
            creator_id: Scope to a single creator, or None for cross-creator.
        """
        model_name = getattr(self._embedder, "model_name", "unknown")
        run = ResearchRun(
            creator_id=creator_id or "cross-creator",
            status="running",
            config_snapshot={
                "pipeline": "clustering",
                "min_cluster_size": self._config.min_cluster_size,
                "umap_seed": self._config.umap_seed,
            },
            prompt_versions={},
            model_versions={"embedder": model_name},
        )
        self._session.add(run)
        await self._session.flush()

        try:
            observations = await self._load_observations(creator_id)
            if not observations:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                await self._session.flush()
                return run

            texts = [o.text for o in observations]
            embeddings = embed_texts(texts, self._embedder)

            await self._store_embeddings(observations, embeddings)

            timestamps = await self._get_timestamps(observations)
            clusters = cluster_observations(
                texts, embeddings, timestamps, self._config
            )
            await self._persist_clusters(observations, clusters, model_name)

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = datetime.now(timezone.utc)
            logger.exception("Clustering pipeline failed")
            raise
        finally:
            await self._session.flush()

        return run

    async def _load_observations(
        self, creator_id: str | None
    ) -> list[ProblemObservation]:
        stmt = select(ProblemObservation)
        if creator_id:
            from corp.core.models.evidence import Evidence

            stmt = (
                stmt.join(Evidence, ProblemObservation.evidence_id == Evidence.id)
                .where(Evidence.research_run_id.isnot(None))
            )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _store_embeddings(
        self,
        observations: list[ProblemObservation],
        embeddings: np.ndarray,
    ) -> None:
        for obs, emb in zip(observations, embeddings):
            obs.embedding = emb.tolist()
        await self._session.flush()

    async def _get_timestamps(
        self, observations: list[ProblemObservation]
    ) -> list[datetime | None]:
        return [obs.created_at if hasattr(obs, "created_at") else None for obs in observations]

    async def _persist_clusters(
        self,
        observations: list[ProblemObservation],
        clusters: list[ClusterResult],
        model_version: str,
    ) -> None:
        for cr in clusters:
            cluster = ProblemCluster(
                label=cr.label,
                description=cr.description,
                frequency=cr.frequency,
                recency_score=cr.recency_score,
                evidence_strength=cr.evidence_strength,
                creator_count=1,
                model_version=model_version,
            )
            self._session.add(cluster)
            await self._session.flush()

            for idx in cr.member_indices:
                obs = observations[idx]
                similarity = 1.0 - (idx / max(len(observations), 1))
                member = ProblemClusterMember(
                    cluster_id=cluster.id,
                    observation_id=obs.id,
                    similarity_score=round(similarity, 4),
                )
                self._session.add(member)

            await self._session.flush()
