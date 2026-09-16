"""Functional check that mirroring a real ProblemObservation row doesn't crash.

Complements test_schema_parity's structural check with an actual round trip
through corp.warmstore.sync.mirror_observations -> WarmStore.put_observations,
against a real (temp-file) SQLite warm store.
"""

from corp.core.models.intelligence import ProblemObservation
from corp.warmstore.store import WarmStore
from corp.warmstore.sync import model_to_dict


async def test_mirror_observations_accepts_sentiment_and_urgency(tmp_path):
    obs = ProblemObservation(
        id="obs-1",
        evidence_id="ev-1",
        text="Runners can't find a knee brace that doesn't slip.",
        category="pain_point",
        is_inferred=False,
        extraction_prompt_version="extract_v3",
        model_version="fake-v1",
        confidence=0.8,
        source_side="audience",
        sentiment="negative",
        urgency="medium",
    )

    store = WarmStore(tmp_path / "warm.db")
    try:
        await store.init_db()
        # This is exactly what mirror_observations() does — the previous
        # (pre-fix) warm-store schema raised CompileError here.
        count = await store.put_observations([model_to_dict(obs)])
        assert count == 1

        counts = await store.count_rows()
        assert counts["problem_observations"] == 1
    finally:
        await store.close()
