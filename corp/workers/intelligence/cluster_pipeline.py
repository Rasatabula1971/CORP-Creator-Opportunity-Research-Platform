"""Clustering pipeline — embed observations, cluster, persist to DB."""

import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import CreatorStatus
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
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    stage,
    start_run,
    supersede,
)

logger = logging.getLogger(__name__)


class ClusterPipeline:
    """Embeds ProblemObservations, clusters them, and persists results.

    A new run for a creator supersedes that creator's previous active clusters.
    Cross-creator runs (``creator_id=None``) supersede previous cross runs only.
    """

    def __init__(
        self,
        embedder: Embedder,
        session: AsyncSession,
        config: ClusteringConfig | None = None,
    ) -> None:
        self._embedder = embedder
        self._session = session
        self._config = config or ClusteringConfig()

    async def run(self, creator_id: str | None = None) -> ResearchRun:
        model_name = getattr(self._embedder, "model_name", "unknown")
        run = await start_run(
            self._session,
            pipeline="clustering",
            creator_id=creator_id,
            config={
                "min_cluster_size": self._config.min_cluster_size,
                "umap_seed": self._config.umap_seed,
            },
            model_versions={"embedder": model_name},
        )
        stats = PipelineStats()

        try:
            async with stage(
                self._session,
                creator_id,
                working=CreatorStatus.CLUSTERING,
                done=CreatorStatus.CLUSTERED,
                run=run,
            ):
                observations = await self._load_observations(creator_id)
                stats.extra["observations"] = len(observations)
                if observations:
                    texts = [o.text for o in observations]
                    embeddings = embed_texts(texts, self._embedder)
                    await self._store_embeddings(observations, embeddings)

                    timestamps = [o.created_at for o in observations]
                    clusters = cluster_observations(texts, embeddings, timestamps, self._config)

                    await supersede(
                        self._session,
                        ProblemCluster,
                        ProblemCluster.creator_id == creator_id
                        if creator_id
                        else ProblemCluster.creator_id.is_(None),
                    )
                    await self._persist_clusters(
                        observations, clusters, model_name, creator_id, embeddings
                    )
                    stats.extra["clusters"] = len(clusters)
                stats.ok()
                await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Clustering pipeline failed")
            raise

        return run

    async def _load_observations(self, creator_id: str | None) -> list[ProblemObservation]:
        # Audience observations only; creator-side ones feed alignment scoring instead.
        stmt = select(ProblemObservation).where(ProblemObservation.source_side == "audience")
        if creator_id:
            stmt = (
                stmt.join(Evidence, ProblemObservation.evidence_id == Evidence.id)
                .join(ResearchRun, ResearchRun.id == Evidence.research_run_id)
                .where(ResearchRun.creator_id == creator_id)
            )
        result = await self._session.execute(stmt.order_by(ProblemObservation.created_at))
        return list(result.scalars().all())

    async def _store_embeddings(
        self,
        observations: list[ProblemObservation],
        embeddings: np.ndarray,
    ) -> None:
        for obs, emb in zip(observations, embeddings, strict=True):
            obs.embedding = emb.tolist()
        await self._session.flush()

    async def _persist_clusters(
        self,
        observations: list[ProblemObservation],
        clusters: list[ClusterResult],
        model_version: str,
        creator_id: str | None,
        embeddings: np.ndarray,
    ) -> None:
        for cr in clusters:
            cluster = ProblemCluster(
                creator_id=creator_id,
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

            member_vecs = embeddings[list(cr.member_indices)]
            centroid = member_vecs.mean(axis=0)
            for idx, sim in zip(
                cr.member_indices, _cosine_to_centroid(member_vecs, centroid), strict=True
            ):
                self._session.add(
                    ProblemClusterMember(
                        cluster_id=cluster.id,
                        observation_id=observations[idx].id,
                        similarity_score=round(float(sim), 4),
                    )
                )

            await self._session.flush()


def _cosine_to_centroid(vectors: np.ndarray, centroid: np.ndarray) -> np.ndarray:
    """Cosine similarity of each row to the centroid, in [0, 1] (clipped)."""
    norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(centroid)
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = np.where(norms > 0, vectors @ centroid / norms, 0.0)
    return np.clip(sims, 0.0, 1.0)
