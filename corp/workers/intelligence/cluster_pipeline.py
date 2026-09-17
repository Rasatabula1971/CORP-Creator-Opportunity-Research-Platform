"""Clustering pipeline — embed observations, cluster, persist to DB, unify topics."""

import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import ContentItem
from corp.core.models.creator import CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.workflow import ResearchRun
from corp.warmstore.sync import mirror_observations
from corp.workers.intelligence.clustering import (
    ClusteringConfig,
    ClusterResult,
    cluster_observations,
)
from corp.workers.intelligence.embeddings import Embedder, embed_texts_async
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
                    embeddings = await embed_texts_async(texts, self._embedder)
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
                    if creator_id:
                        # Roll the cluster labels into ContentItem.topics so the
                        # dashboard's per-content topic list carries both the
                        # LLM-classified topics and the cluster-derived ones.
                        # Cross-creator runs skip this since topics attach to
                        # one creator's content, not to shared clusters.
                        await self._unify_topics(creator_id, clusters)
                        run.record_step("unify_topics", "completed")
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
        # Extraction mirrored these rows before they carried vectors; re-mirror
        # so the warm store's embedding column is populated (INSERT OR REPLACE).
        await mirror_observations(observations)

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


    async def _unify_topics(
        self,
        creator_id: str,
        clusters: list[ClusterResult],
    ) -> None:
        """Merge cluster labels into the creator's ContentItem.topics list.

        Produces a unified per-item topic list: cluster-derived topics (with
        frequency and evidence strength) get merged with any existing LLM-
        classified topics, deduplicated case-insensitively, and capped at 15.
        Every content item for the creator receives the same unified list so
        the front-end can render one topic pill row per creator regardless of
        which content item it displays.
        """
        result = await self._session.execute(
            select(ContentItem).where(ContentItem.creator_id == creator_id)
        )
        content_items = list(result.scalars().all())
        if not content_items:
            return

        cluster_topics = [
            {
                "name": cr.label,
                "confidence": round(cr.evidence_strength, 2),
                "evidence_count": cr.frequency,
                "source": "cluster",
            }
            for cr in clusters
        ]
        cluster_topics.sort(key=lambda t: t["evidence_count"], reverse=True)

        existing_topics = content_items[0].topics or []
        cluster_names_lower = {t["name"].lower() for t in cluster_topics}
        unified = list(cluster_topics)
        for et in existing_topics:
            if not isinstance(et, dict):
                continue
            if et.get("source") == "cluster":
                # Labels this method wrote on a previous run belong to clusters
                # that were just superseded; rebuild them from ``clusters``.
                continue
            if (et.get("name") or "").lower() in cluster_names_lower:
                continue
            et_copy = dict(et)
            et_copy.setdefault("source", "llm")
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


def _cosine_to_centroid(vectors: np.ndarray, centroid: np.ndarray) -> np.ndarray:
    """Cosine similarity of each row to the centroid, in [0, 1] (clipped)."""
    norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(centroid)
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = np.where(norms > 0, vectors @ centroid / norms, 0.0)
    return np.clip(sims, 0.0, 1.0)
