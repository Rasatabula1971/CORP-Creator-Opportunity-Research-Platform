"""Unit tests for clustering — uses synthetic embeddings with known structure."""

from datetime import UTC, datetime

import numpy as np

from corp.workers.intelligence.clustering import (
    ClusteringConfig,
    ClusterResult,
    _generate_label,
    _pick_representative,
    cluster_observations,
)


def _make_clustered_embeddings(
    n_per_cluster: int = 10,
    n_clusters: int = 3,
    dim: int = 10,
    seed: int = 42,
) -> tuple[list[str], np.ndarray]:
    """Generate synthetic embeddings with clear cluster structure."""
    rng = np.random.RandomState(seed)
    texts: list[str] = []
    embeddings: list[np.ndarray] = []

    cluster_themes = [
        "battery life drains quickly on this phone",
        "camera quality is terrible in low light",
        "shipping takes too long for delivery",
    ]

    for c in range(n_clusters):
        center = rng.randn(dim).astype(np.float32) * 10
        for i in range(n_per_cluster):
            point = center + rng.randn(dim).astype(np.float32) * 0.1
            embeddings.append(point)
            texts.append(f"{cluster_themes[c % len(cluster_themes)]} variation {i}")

    return texts, np.vstack(embeddings)


async def test_cluster_observations_finds_clusters():
    texts, embeddings = _make_clustered_embeddings(n_per_cluster=10, n_clusters=3)
    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3)

    results = cluster_observations(texts, embeddings, config=config)

    assert len(results) >= 1
    assert all(isinstance(r, ClusterResult) for r in results)
    total_members = sum(r.frequency for r in results)
    assert total_members <= len(texts)


async def test_cluster_observations_too_few():
    texts = ["one", "two"]
    embeddings = np.random.randn(2, 10).astype(np.float32)

    results = cluster_observations(texts, embeddings)
    assert results == []


async def test_cluster_result_fields():
    texts, embeddings = _make_clustered_embeddings(n_per_cluster=10, n_clusters=2, dim=10)
    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3)

    results = cluster_observations(texts, embeddings, config=config)

    if results:
        r = results[0]
        assert r.label
        assert r.description
        assert r.frequency >= config.min_cluster_size
        assert 0.0 <= r.evidence_strength <= 1.0
        assert len(r.member_indices) == r.frequency


async def test_cluster_recency_scoring():
    texts, embeddings = _make_clustered_embeddings(n_per_cluster=10, n_clusters=2, dim=10)
    now = datetime.now(UTC)
    timestamps = [now] * len(texts)
    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3)

    results = cluster_observations(texts, embeddings, timestamps, config=config)

    if results:
        assert results[0].recency_score > 0.9


async def test_recency_distinguishes_no_data_from_old_data():
    """0.0 must mean "no timestamp data" specifically — a real but old
    timestamp must decay to a small positive value, never collide with the
    no-data sentinel, and different old ages must stay distinguishable from
    each other (previously both saturated to an identical 0.0)."""
    from datetime import timedelta

    texts, embeddings = _make_clustered_embeddings(n_per_cluster=10, n_clusters=1, dim=10)
    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3)

    no_timestamps = cluster_observations(texts, embeddings, None, config=config)
    now = datetime.now(UTC)
    old_400 = cluster_observations(
        texts, embeddings, [now - timedelta(days=400)] * len(texts), config=config
    )
    old_4000 = cluster_observations(
        texts, embeddings, [now - timedelta(days=4000)] * len(texts), config=config
    )

    if no_timestamps and old_400 and old_4000:
        assert no_timestamps[0].recency_score == 0.0
        assert 0.0 < old_4000[0].recency_score < old_400[0].recency_score < 1.0


async def test_cluster_determinism():
    """Same input + same seed → same output."""
    texts, embeddings = _make_clustered_embeddings(n_per_cluster=10, n_clusters=2, dim=10, seed=99)
    config = ClusteringConfig(min_cluster_size=3, min_samples=2, umap_n_components=3, umap_seed=42)

    r1 = cluster_observations(texts, embeddings, config=config)
    r2 = cluster_observations(texts, embeddings, config=config)

    assert len(r1) == len(r2)
    for a, b in zip(r1, r2):
        assert a.frequency == b.frequency
        assert sorted(a.member_indices) == sorted(b.member_indices)


async def test_pick_representative():
    texts = ["short", "this is a longer text", "medium text"]
    assert _pick_representative(texts) == "this is a longer text"


async def test_pick_representative_empty():
    assert _pick_representative([]) == ""


async def test_generate_label():
    texts = [
        "battery drains fast on phone",
        "phone battery issues draining",
        "battery problem with phone charging",
    ]
    label = _generate_label(texts)
    assert len(label) > 0
    assert "battery" in label.lower() or "phone" in label.lower()


async def test_generate_label_empty():
    assert _generate_label([]) == "Unlabeled cluster"


def test_tiny_input_clusters_without_umap():
    """Fewer points than UMAP can initialise from (<= n_components + 1) still
    cluster: two tight groups of two, min_cluster_size=2."""
    rng = np.random.RandomState(1)
    a = rng.randn(4, 8).astype(np.float32) * 0.01
    a[:2, 0] += 10.0
    a[2:, 1] += 10.0
    texts = ["battery a", "battery b", "camera a", "camera b"]
    clusters = cluster_observations(
        texts, a, config=ClusteringConfig(min_cluster_size=2, min_samples=1)
    )
    assert len(clusters) == 2
    assert sorted(len(c.member_indices) for c in clusters) == [2, 2]
