"""Clustering pipeline — embed observations, cluster, persist to DB, unify topics."""

import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import ContentItem
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.evidence import Evidence
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
from corp.workers.intelligence.embeddings import Embedder, embed_texts

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
            creator_id=creator_id,
            status="running",
            started_at=datetime.now(timezone.utc),
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

        if creator_id:
            await self._transition_status(creator_id, CreatorStatus.CLUSTERING)

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
            await self._persist_clusters(observations, clusters, embeddings, model_name)

            if creator_id and clusters:
                await self._unify_topics(creator_id, clusters)

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            if creator_id:
                await self._transition_status(creator_id, CreatorStatus.CLUSTERED)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = datetime.now(timezone.utc)
            logger.exception("Clustering pipeline failed")
            raise
        finally:
            await self._session.flush()

        return run

    async def _transition_status(self, creator_id: str, status: CreatorStatus) -> None:
        result = await self._session.execute(
            select(Creator).where(Creator.id == creator_id)
        )
        creator = result.scalars().first()
        if creator:
            creator.status = status
            await self._session.flush()

    async def _load_observations(
        self, creator_id: str | None
    ) -> list[ProblemObservation]:
        stmt = select(ProblemObservation)
        if creator_id:
            stmt = (
                stmt.join(Evidence, ProblemObservation.evidence_id == Evidence.id)
                .join(ResearchRun, Evidence.research_run_id == ResearchRun.id)
                .where(ResearchRun.creator_id == creator_id)
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
        embeddings: np.ndarray,
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

            centroid = np.mean(
                [embeddings[i] for i in cr.member_indices], axis=0
            )
            centroid_norm = np.linalg.norm(centroid)
            for idx in cr.member_indices:
                obs = observations[idx]
                emb = embeddings[idx]
                emb_norm = np.linalg.norm(emb)
                if centroid_norm > 0 and emb_norm > 0:
                    similarity = float(np.dot(emb, centroid) / (emb_norm * centroid_norm))
                else:
                    similarity = 0.0
                member = ProblemClusterMember(
                    cluster_id=cluster.id,
                    observation_id=obs.id,
                    similarity_score=round(similarity, 4),
                )
                self._session.add(member)

            await self._session.flush()

    async def _unify_topics(
        self,
        creator_id: str,
        clusters: list[ClusterResult],
    ) -> None:
        """Merge BERTopic cluster labels into the creator's ContentItem topics.

        Produces a unified topic list: cluster-derived topics (with frequency
        and evidence strength) are merged with any existing LLM-classified
        topics, deduplicating by similarity.
        """
        result = await self._session.execute(
            select(ContentItem).where(ContentItem.creator_id == creator_id)
        )
        content_items = result.scalars().all()
        if not content_items:
            return

        cluster_topics = []
        for cr in clusters:
            cluster_topics.append({
                "name": cr.label,
                "confidence": round(cr.evidence_strength, 2),
                "evidence_count": cr.frequency,
                "source": "cluster",
            })

        cluster_topics.sort(key=lambda t: t["evidence_count"], reverse=True)

        existing_topics = content_items[0].topics if content_items[0].topics else []

        unified = list(cluster_topics)
        cluster_names_lower = {t["name"].lower() for t in cluster_topics}
        for et in existing_topics:
            if isinstance(et, dict) and et.get("name", "").lower() not in cluster_names_lower:
                et_copy = dict(et)
                et_copy["source"] = "llm"
                unified.append(et_copy)

        unified = unified[:15]

        for ci in content_items:
            ci.topics = unified
        await self._session.flush()
        logger.info(
            "Unified topics for creator %s: %d cluster + %d LLM → %d total",
            creator_id,
            len(cluster_topics),
            len(existing_topics),
            len(unified),
        )
