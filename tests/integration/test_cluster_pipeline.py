"""Integration tests for ClusterPipeline against real Postgres."""

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator
from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.cluster_pipeline import ClusterPipeline
from corp.workers.intelligence.clustering import ClusteringConfig
from corp.workers.intelligence.embeddings import EMBEDDING_DIM


class FakeEmbedder:
    """Returns embeddings with clear cluster structure for testing."""

    model_name = "fake-embedder"

    def encode(self, texts: list[str]) -> np.ndarray:
        rng = np.random.RandomState(42)
        n = len(texts)
        embeddings = np.zeros((n, EMBEDDING_DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            if "battery" in text.lower():
                center = rng.randn(EMBEDDING_DIM).astype(np.float32) * 0.01
                center[0] = 10.0
            elif "camera" in text.lower():
                center = rng.randn(EMBEDDING_DIM).astype(np.float32) * 0.01
                center[1] = 10.0
            else:
                center = rng.randn(EMBEDDING_DIM).astype(np.float32) * 0.01
                center[2] = 10.0
            embeddings[i] = center
        return embeddings


async def _seed_observations(
    session: AsyncSession, n_per_group: int = 5
) -> tuple[Creator, list[ProblemObservation]]:
    """Create a creator with multiple ProblemObservation groups."""
    creator = Creator(name="ClusterTest", niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()

    run = ResearchRun(
        creator_id=creator.id,
        status="completed",
        config_snapshot={},
        prompt_versions={},
        model_versions={},
    )
    session.add(run)
    await session.flush()

    observations: list[ProblemObservation] = []
    themes = [
        ("battery drains fast", "problem"),
        ("camera quality poor", "problem"),
        ("shipping slow", "problem"),
    ]

    for theme_text, category in themes:
        for i in range(n_per_group):
            evidence = Evidence(
                source_type="comment",
                source_id=f"ext_{theme_text.split()[0]}_{i}",
                source_platform="youtube",
                raw_text=f"{theme_text} issue #{i}",
                access_method=AccessMethod.OFFICIAL,
                compliance_status=ComplianceStatus.COMPLIANT,
                research_run_id=run.id,
                origin=EvidenceOrigin.OBSERVATION,
                evidence_type=EvidenceType.PROBLEM,
            )
            session.add(evidence)
            await session.flush()

            obs = ProblemObservation(
                evidence_id=evidence.id,
                text=f"{theme_text} issue #{i}",
                category=category,
                is_inferred=False,
                extraction_prompt_version="extract_v1",
                model_version="test",
                confidence=0.9,
            )
            session.add(obs)
            observations.append(obs)

    await session.flush()
    return creator, observations


@pytest.mark.asyncio
async def test_cluster_pipeline_creates_run(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed_observations(session)

    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3)
    pipeline = ClusterPipeline(FakeEmbedder(), session, config)

    run = await pipeline.run(creator.id)

    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.model_versions["embedder"] == "fake-embedder"


@pytest.mark.asyncio
async def test_cluster_pipeline_stores_embeddings(clean_db: AsyncSession):
    session = clean_db
    creator, observations = await _seed_observations(session)

    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3)
    pipeline = ClusterPipeline(FakeEmbedder(), session, config)

    await pipeline.run(creator.id)

    result = await session.execute(select(ProblemObservation))
    all_obs = result.scalars().all()

    embedded_count = sum(1 for o in all_obs if o.embedding is not None)
    assert embedded_count == len(observations)


@pytest.mark.asyncio
async def test_cluster_pipeline_creates_clusters(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed_observations(session)

    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3)
    pipeline = ClusterPipeline(FakeEmbedder(), session, config)

    await pipeline.run(creator.id)

    result = await session.execute(select(ProblemCluster))
    clusters = result.scalars().all()

    assert len(clusters) >= 1
    for c in clusters:
        assert c.label
        assert c.frequency >= config.min_cluster_size
        assert c.model_version == "fake-embedder"


@pytest.mark.asyncio
async def test_cluster_pipeline_creates_members(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed_observations(session)

    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3)
    pipeline = ClusterPipeline(FakeEmbedder(), session, config)

    await pipeline.run(creator.id)

    result = await session.execute(select(ProblemClusterMember))
    members = result.scalars().all()

    assert len(members) >= 1
    for m in members:
        assert m.similarity_score > 0


@pytest.mark.asyncio
async def test_cluster_pipeline_empty_observations(clean_db: AsyncSession):
    session = clean_db
    creator = Creator(name="Empty", niche="test", discovery_source="manual")
    session.add(creator)
    await session.flush()

    config = ClusteringConfig(min_cluster_size=3)
    pipeline = ClusterPipeline(FakeEmbedder(), session, config)

    run = await pipeline.run(creator.id)
    assert run.status == "completed"

    result = await session.execute(select(ProblemCluster))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_cluster_pipeline_failure_marks_run_failed(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed_observations(session)

    class BrokenEmbedder:
        model_name = "broken"

        def encode(self, texts: list[str]) -> np.ndarray:
            raise RuntimeError("Embedder crashed")

    config = ClusteringConfig(min_cluster_size=3)
    pipeline = ClusterPipeline(BrokenEmbedder(), session, config)

    with pytest.raises(RuntimeError, match="Embedder crashed"):
        await pipeline.run(creator.id)

    result = await session.execute(
        select(ResearchRun).where(ResearchRun.config_snapshot["pipeline"].astext == "clustering")
    )
    run = result.scalar_one()
    assert run.status == "failed"
    assert "RuntimeError" in run.error_message
    assert "Embedder crashed" not in run.error_message, "exception text stays in the log"
