"""Embeddings must survive the Postgres -> warm store mirror as float32 bytes.

The cluster pipeline assigns ``obs.embedding = ndarray.tolist()`` (a list of
Python floats) and re-mirrors; rows loaded back from pgvector carry a numpy
array instead. ``mirror_observations`` must handle both and
``WarmStore.get_observation_embeddings`` must return the vector intact.
"""

from pathlib import Path

import numpy as np
import pytest

from corp.core.models.intelligence import ProblemObservation
from corp.warmstore import sync
from corp.warmstore.store import WarmStore
from corp.warmstore.sync import embedding_to_bytes, mirror_observations


def _obs(obs_id: str, embedding: list[float] | np.ndarray | None) -> ProblemObservation:
    return ProblemObservation(
        id=obs_id,
        evidence_id="ev-1",
        text="Runners can't find a knee brace that doesn't slip.",
        category="pain_point",
        is_inferred=False,
        extraction_prompt_version="extract_v3",
        model_version="fake-v1",
        confidence=0.8,
        source_side="audience",
        embedding=embedding,
    )


def test_embedding_to_bytes_handles_list_ndarray_bytes_and_none() -> None:
    vec = [0.25, -1.5, 3.0]
    expected = np.asarray(vec, dtype="<f4").tobytes()

    assert embedding_to_bytes(vec) == expected
    assert embedding_to_bytes(np.asarray(vec, dtype=np.float64)) == expected
    assert embedding_to_bytes(expected) == expected
    assert embedding_to_bytes(None) is None


@pytest.mark.parametrize("as_ndarray", [False, True])
async def test_mirror_observations_round_trips_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, as_ndarray: bool
) -> None:
    vec = [0.1, 0.2, 0.3, 0.4]
    embedding = np.asarray(vec, dtype=np.float32) if as_ndarray else vec

    store = WarmStore(tmp_path / "warm.db")
    monkeypatch.setattr(sync, "_store", store)
    try:
        # First mirror happens at extraction time, before any vector exists.
        await mirror_observations([_obs("obs-1", None)])
        assert await store.get_observation_embeddings(["obs-1"]) == {}

        # Re-mirror after the cluster pipeline stores the vector (INSERT OR REPLACE).
        await mirror_observations([_obs("obs-1", embedding)])

        blobs = await store.get_observation_embeddings(["obs-1"])
        assert set(blobs) == {"obs-1"}
        restored = np.frombuffer(blobs["obs-1"], dtype="<f4")
        np.testing.assert_allclose(restored, np.asarray(vec, dtype=np.float32))

        counts = await store.count_rows()
        assert counts["problem_observations"] == 1
    finally:
        await store.close()
