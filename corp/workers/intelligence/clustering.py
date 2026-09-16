"""Problem observation clustering via BERTopic (UMAP + HDBSCAN + c-TF-IDF)."""

import logging
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
    """Cluster observation texts using BERTopic (UMAP + HDBSCAN + c-TF-IDF).

    Uses pre-computed embeddings. BERTopic handles dimensionality reduction,
    density-based clustering, and c-TF-IDF label generation internally.

    Args:
        texts: ProblemObservation.text values.
        embeddings: (N, D) float32 embedding matrix.
        timestamps: Optional timestamps for recency scoring.
        config: Clustering configuration.

    Returns:
        List of ClusterResult, one per discovered cluster (noise excluded).
    """
    cfg = config or ClusteringConfig()

    if len(texts) < cfg.min_cluster_size:
        logger.info("Too few observations (%d) to cluster", len(texts))
        return []

    topic_assignments = _fit_bertopic(texts, embeddings, cfg)
    return _build_clusters(texts, topic_assignments, timestamps)


def _fit_bertopic(
    texts: list[str],
    embeddings: np.ndarray,
    cfg: ClusteringConfig,
) -> list[int]:
    """Run BERTopic with pre-computed embeddings and return topic assignments."""
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

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

    umap_model = UMAP(
        n_components=max(n_components, 2),
        n_neighbors=max(n_neighbors, 2),
        random_state=cfg.umap_seed,
        metric="cosine",
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=cfg.min_cluster_size,
        min_samples=cfg.min_samples,
        metric="euclidean",
    )
    vectorizer = CountVectorizer(stop_words="english", min_df=1)

    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer,
        calculate_probabilities=False,
    )

    topics, _ = topic_model.fit_transform(texts, embeddings=embeddings)

    _TOPIC_MODEL_CACHE.model = topic_model
    return list(topics)


class _TopicModelCache:
    """Holds the last fitted BERTopic model for label extraction."""
    model = None

_TOPIC_MODEL_CACHE = _TopicModelCache()


def get_topic_labels() -> dict[int, str]:
    """Return topic_id → c-TF-IDF label mapping from the last fit."""
    model = _TOPIC_MODEL_CACHE.model
    if model is None:
        return {}
    labels: dict[int, str] = {}
    for topic_id in model.get_topic_info()["Topic"]:
        if topic_id == -1:
            continue
        top_words = model.get_topic(topic_id)
        if top_words:
            labels[topic_id] = " ".join(w for w, _ in top_words[:4]).title()
        else:
            labels[topic_id] = f"Topic {topic_id}"
    return labels


def _build_clusters(
    texts: list[str],
    topic_assignments: list[int],
    timestamps: list[datetime | None] | None,
) -> list[ClusterResult]:
    now = datetime.now(UTC)
    unique_labels = set(labels)
    unique_labels.discard(-1)

    model = _TOPIC_MODEL_CACHE.model
    results: list[ClusterResult] = []
    for label_id in sorted(unique_labels):
        indices = [i for i, lbl in enumerate(labels) if lbl == label_id]
        cluster_texts = [texts[i] for i in indices]

        if model is not None:
            top_words = model.get_topic(topic_id)
            if top_words:
                label_str = " ".join(w for w, _ in top_words[:4]).title()
            else:
                label_str = f"Topic {topic_id}"
        else:
            label_str = f"Topic {topic_id}"

        representative = _pick_representative(cluster_texts)

        recency = 0.0
        if timestamps:
            cluster_ts = [timestamps[i] for i in indices if timestamps[i] is not None]
            if cluster_ts:
                most_recent = max(cluster_ts)
                days_ago = (now - most_recent).total_seconds() / 86400
                recency = max(0.0, 1.0 - (days_ago / 365.0))

        evidence_strength = min(1.0, len(indices) / 10.0)

        results.append(
            ClusterResult(
                label=label_str,
                description=representative,
                member_indices=indices,
                frequency=len(indices),
                recency_score=round(recency, 4),
                evidence_strength=round(evidence_strength, 4),
            )
        )

    logger.info(
        "BERTopic: %d observations → %d clusters (%d noise)",
        len(texts),
        len(results),
        sum(1 for lbl in labels if lbl == -1),
    )
    return results


def _pick_representative(texts: list[str]) -> str:
    """Pick the longest text as the representative description."""
    return max(texts, key=len) if texts else ""
