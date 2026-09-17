"""Unit tests for ClusterPipeline persistence helpers — no database."""

import numpy as np

from corp.core.models.content import ContentItem
from corp.core.models.intelligence import ProblemObservation
from corp.workers.intelligence import cluster_pipeline
from corp.workers.intelligence.cluster_pipeline import ClusterPipeline
from corp.workers.intelligence.clustering import ClusterResult


class _Scalars:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class FakeSession:
    def __init__(self, rows=()) -> None:
        self._rows = rows
        self.flushes = 0

    async def execute(self, stmt):
        return _Result(self._rows)

    async def flush(self) -> None:
        self.flushes += 1


def _cluster(label: str, frequency: int = 1) -> ClusterResult:
    return ClusterResult(
        label=label,
        description="",
        member_indices=[0],
        frequency=frequency,
        recency_score=0.5,
        evidence_strength=0.7,
    )


async def test_unify_topics_drops_previous_runs_cluster_labels():
    stale_topics = [
        {"name": "old cluster", "source": "cluster", "evidence_count": 9},
        {"name": "Budgeting", "confidence": 0.9},  # LLM topic without a source tag
        {"name": "Taxes", "source": "llm"},
        {"name": "tracking expenses", "source": "llm"},  # collides with a live cluster
        "garbage",
    ]
    items = [ContentItem(creator_id="c", topics=stale_topics), ContentItem(creator_id="c")]
    session = FakeSession(items)
    pipe = ClusterPipeline(embedder=None, session=session)  # type: ignore[arg-type]

    await pipe._unify_topics("c", [_cluster("Tracking Expenses", 3), _cluster("Invoicing", 2)])

    names = [t["name"] for t in items[0].topics]
    assert names == ["Tracking Expenses", "Invoicing", "Budgeting", "Taxes"]
    assert all(t["source"] == "cluster" for t in items[0].topics[:2])
    assert items[0].topics[2]["source"] == "llm"
    assert items[1].topics == items[0].topics
    assert session.flushes == 1


async def test_unify_topics_is_stable_across_reruns():
    items = [ContentItem(creator_id="c", topics=[{"name": "Taxes", "source": "llm"}])]
    pipe = ClusterPipeline(embedder=None, session=FakeSession(items))  # type: ignore[arg-type]
    for _ in range(3):
        await pipe._unify_topics("c", [_cluster("Invoicing")])
    assert [t["name"] for t in items[0].topics] == ["Invoicing", "Taxes"]


async def test_store_embeddings_sets_vectors_then_remirrors(monkeypatch):
    mirrored: list = []

    async def fake_mirror(rows):
        mirrored.append(list(rows))

    monkeypatch.setattr(cluster_pipeline, "mirror_observations", fake_mirror)
    session = FakeSession()
    pipe = ClusterPipeline(embedder=None, session=session)  # type: ignore[arg-type]
    observations = [ProblemObservation(text="a"), ProblemObservation(text="b")]
    embeddings = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)

    await pipe._store_embeddings(observations, embeddings)

    assert observations[0].embedding == [np.float32(0.1), np.float32(0.2)]
    assert isinstance(observations[0].embedding, list)
    assert mirrored == [observations]
    assert session.flushes == 1
