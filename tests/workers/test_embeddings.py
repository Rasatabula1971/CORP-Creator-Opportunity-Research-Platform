"""Unit tests for embeddings module — no model download needed."""

import numpy as np

from corp.workers.intelligence.embeddings import EMBEDDING_DIM, embed_texts


class FakeEmbedder:
    """Deterministic embedder returning fixed-dimension vectors."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        rng = np.random.RandomState(42)
        return rng.randn(len(texts), self._dim).astype(np.float32)


async def test_embed_texts_basic():
    embedder = FakeEmbedder()
    texts = ["problem one", "problem two", "problem three"]
    result = embed_texts(texts, embedder)

    assert result.shape == (3, EMBEDDING_DIM)
    assert result.dtype == np.float32


async def test_embed_texts_empty():
    embedder = FakeEmbedder()
    result = embed_texts([], embedder)

    assert result.shape == (0, EMBEDDING_DIM)
    assert result.dtype == np.float32


async def test_embed_texts_single():
    embedder = FakeEmbedder()
    result = embed_texts(["one text"], embedder)

    assert result.shape == (1, EMBEDDING_DIM)


async def test_embed_texts_batching():
    call_count = 0

    class CountingEmbedder:
        def encode(self, texts: list[str]) -> np.ndarray:
            nonlocal call_count
            call_count += 1
            return np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)

    texts = [f"text_{i}" for i in range(150)]
    result = embed_texts(texts, CountingEmbedder(), batch_size=64)

    assert result.shape == (150, EMBEDDING_DIM)
    assert call_count == 3  # 64 + 64 + 22


async def test_embed_texts_deterministic():
    embedder = FakeEmbedder()
    texts = ["hello world", "test"]
    r1 = embed_texts(texts, embedder)
    r2 = embed_texts(texts, embedder)

    np.testing.assert_array_equal(r1, r2)
