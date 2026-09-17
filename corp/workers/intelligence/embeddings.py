"""Embedding generation for ProblemObservation text using sentence-transformers."""

import asyncio
import logging
import threading
from typing import Any, Protocol

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
        # Loaded lazily on first encode() so that the multi-second torch model
        # load happens on the worker thread embed_texts_async() runs on, not on
        # the API event loop when a job constructs the pipeline.
        self._model: object | None = None
        self._model_name = model_name
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self._model_name)
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        embs = self._get_model().encode(texts, show_progress_bar=False, convert_to_numpy=True)
        return np.asarray(embs)


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


async def embed_texts_async(
    texts: list[str],
    embedder: Embedder,
    batch_size: int = 64,
) -> np.ndarray:
    """``embed_texts`` on a worker thread.

    Pipelines run on the API process's event loop (FastAPI BackgroundTasks),
    and a sentence-transformers encode of a few hundred texts blocks for
    seconds. Offloading keeps /health and job polling responsive meanwhile.
    """
    return await asyncio.to_thread(embed_texts, texts, embedder, batch_size)
