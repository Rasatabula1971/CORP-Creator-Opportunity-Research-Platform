"""Embedding generation for ProblemObservation text using sentence-transformers."""

import logging
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


class Embedder(Protocol):
    """Protocol for anything that can embed text into vectors."""

    def encode(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Production embedder using sentence-transformers (local, free)."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(texts, show_progress_bar=False, convert_to_numpy=True)


def embed_texts(
    texts: list[str],
    embedder: Embedder,
    batch_size: int = 64,
) -> np.ndarray:
    """Embed a list of texts in batches.

    Returns an (N, EMBEDDING_DIM) float32 array.
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    all_embeddings: list[np.ndarray] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        embs = embedder.encode(batch)
        all_embeddings.append(np.asarray(embs, dtype=np.float32))

    result = np.vstack(all_embeddings)
    logger.info("Embedded %d texts → shape %s", len(texts), result.shape)
    return result
