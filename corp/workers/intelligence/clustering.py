"""Problem observation clustering via UMAP + HDBSCAN with c-TF-IDF labeling."""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

logger = logging.getLogger(__name__)

UMAP_SEED = 42
MIN_CLUSTER_SIZE = 3
MIN_SAMPLES = 2


@dataclass(frozen=True, slots=True)
class ClusterResult:
    """Output of the clustering step."""

    label: str
    description: str
    member_indices: list[int]
    frequency: int
    recency_score: float
    evidence_strength: float


@dataclass
class ClusteringConfig:
    """Tunable clustering parameters."""

    min_cluster_size: int = MIN_CLUSTER_SIZE
    min_samples: int = MIN_SAMPLES
    umap_n_components: int = 5
    umap_n_neighbors: int = 15
    umap_seed: int = UMAP_SEED


def cluster_observations(
    texts: list[str],
    embeddings: np.ndarray,
    timestamps: list[datetime | None] | None = None,
    config: ClusteringConfig | None = None,
) -> list[ClusterResult]:
    """Cluster observation texts using UMAP + HDBSCAN.

    Args:
        texts: ProblemObservation.text values.
        embeddings: (N, D) float32 embedding matrix.
        timestamps: Optional timestamps for recency scoring.
        config: Clustering configuration.

    Returns:
        List of ClusterResult, one per discovered cluster (noise excluded).
    """
    if len(texts) < (config or ClusteringConfig()).min_cluster_size:
        logger.info("Too few observations (%d) to cluster", len(texts))
        return []

    cfg = config or ClusteringConfig()

    reduced = _reduce_dimensions(embeddings, cfg)
    labels = _run_hdbscan(reduced, cfg)
    return _build_clusters(texts, labels, timestamps)


def _reduce_dimensions(embeddings: np.ndarray, cfg: ClusteringConfig) -> np.ndarray:
    import umap

    n_samples = embeddings.shape[0]
    if n_samples <= cfg.umap_n_components + 1:
        # UMAP's spectral initialisation needs more points than target
        # dimensions (scipy eigsh: k >= N); at this size the raw embedding
        # space is small enough for HDBSCAN directly. Seen with a 4-item
        # discovery evidence set (Slice 8).
        logger.info("Skipping UMAP for %d samples; clustering raw embeddings", n_samples)
        return np.asarray(embeddings, dtype=np.float32)
    n_components = min(cfg.umap_n_components, n_samples - 1)
    n_neighbors = min(cfg.umap_n_neighbors, n_samples - 1)

    reducer = umap.UMAP(
        n_components=max(n_components, 2),
        n_neighbors=max(n_neighbors, 2),
        random_state=cfg.umap_seed,
        metric="cosine",
    )
    return reducer.fit_transform(embeddings)


def _run_hdbscan(reduced: np.ndarray, cfg: ClusteringConfig) -> np.ndarray:
    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=cfg.min_cluster_size,
        min_samples=cfg.min_samples,
        metric="euclidean",
    )
    clusterer.fit(reduced)
    return clusterer.labels_


def _build_clusters(
    texts: list[str],
    labels: np.ndarray,
    timestamps: list[datetime | None] | None,
) -> list[ClusterResult]:
    now = datetime.now(UTC)
    unique_labels = set(labels)
    unique_labels.discard(-1)

    results: list[ClusterResult] = []
    for label_id in sorted(unique_labels):
        indices = [i for i, lbl in enumerate(labels) if lbl == label_id]
        cluster_texts = [texts[i] for i in indices]

        representative = _pick_representative(cluster_texts)
        label_str = _generate_label(cluster_texts)

        # 0.0 is reserved to mean "no timestamp data at all" (the case below
        # this block, when no cluster member has a timestamp). A real, however
        # old, date decays exponentially and only approaches but never reaches
        # 0.0, so a 400-day-old cluster and a 4000-day-old cluster stay
        # distinguishable instead of both saturating to the same value — and
        # neither one is ever confused with "we have no idea how old this is".
        recency = 0.0
        if timestamps:
            cluster_ts = [timestamps[i] for i in indices if timestamps[i] is not None]
            if cluster_ts:
                most_recent = max(cluster_ts)
                days_ago = max(0.0, (now - most_recent).total_seconds() / 86400)
                recency = math.exp(-days_ago / 365.0)

        evidence_strength = min(1.0, len(indices) / 10.0)

        results.append(
            ClusterResult(
                label=label_str,
                description=representative,
                member_indices=indices,
                frequency=len(indices),
                # 6 decimals: 4 would round anything past ~3 years old to
                # exactly 0.0, colliding with the "no timestamp data" sentinel.
                recency_score=round(recency, 6),
                evidence_strength=round(evidence_strength, 4),
            )
        )

    logger.info(
        "Clustering: %d observations → %d clusters (%d noise)",
        len(texts),
        len(results),
        sum(1 for lbl in labels if lbl == -1),
    )
    return results


def _pick_representative(texts: list[str]) -> str:
    """Pick the longest text as the representative description."""
    return max(texts, key=len) if texts else ""


def _generate_label(texts: list[str]) -> str:
    """Generate a cluster label from the most common words across texts."""
    from collections import Counter

    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "about", "like",
        "through", "after", "over", "between", "out", "against", "during",
        "without", "before", "under", "around", "among", "and", "but", "or",
        "so", "if", "than", "too", "very", "just", "that", "this", "it",
        "i", "my", "me", "we", "you", "your", "he", "she", "they", "them",
        "not", "no", "don't", "doesn't", "didn't", "won't", "can't",
    }
    word_counts: Counter[str] = Counter()
    for text in texts:
        words = text.lower().split()
        word_counts.update(w for w in words if w not in stop_words and len(w) > 2)

    top = word_counts.most_common(4)
    if not top:
        return "Unlabeled cluster"
    return " ".join(w for w, _ in top).title()
