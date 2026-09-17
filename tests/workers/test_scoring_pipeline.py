"""Unit tests for ScoringPipeline configuration plumbing — no database."""

from corp.core.models.intelligence import ProblemCluster
from corp.core.models.scoring import ConfidenceBand
from corp.core.scoring.engine import load_scoring_rules
from corp.workers.intelligence import scoring_pipeline
from corp.workers.intelligence.scoring_pipeline import (
    ClusterContext,
    CreatorContext,
    ScoringPipeline,
)


class FakeSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass


def _creator_context() -> CreatorContext:
    return CreatorContext(
        subscriber_count=1000,
        audience_platforms=["youtube"],
        creator_observation_tokens=[],
        commerce_page_tokens=[],
        commerce_signal_count=0,
        monetisation={},
        engagement_rate_by_platform={},
        follower_growth=None,
    )


async def test_score_opportunity_passes_yaml_confidence_thresholds(monkeypatch):
    recorded: list[dict] = []

    def fake_band(**kwargs):
        recorded.append(kwargs)
        return ConfidenceBand.LOW

    async def _none(*args, **kwargs):
        return None

    async def _cluster_ctx(cluster):
        return ClusterContext(
            member_count=4, platforms={"youtube"}, compliant_platforms={"youtube"}
        )

    async def _strengths(cluster_id):
        return []

    monkeypatch.setattr(scoring_pipeline, "compute_confidence_band", fake_band)
    monkeypatch.setattr(scoring_pipeline, "mirror_scores", _none)

    pipe = ScoringPipeline(FakeSession())  # type: ignore[arg-type]
    pipe._get_signal = _none  # type: ignore[method-assign]
    pipe._load_cluster_context = _cluster_ctx  # type: ignore[method-assign]
    pipe._get_competitor_strengths = _strengths  # type: ignore[method-assign]
    pipe._previous_frequency = _none  # type: ignore[method-assign]

    cluster = ProblemCluster(id="c-1", label="x", frequency=3, recency_score=0.5)
    opp = await pipe._score_opportunity(cluster, "creator-1", _creator_context(), "run-1")

    expected = load_scoring_rules("rules/scoring.yaml")["confidence_thresholds"]
    assert expected is not None
    assert len(recorded) == 1
    assert recorded[0]["thresholds"] == expected
    assert opp.confidence_band == ConfidenceBand.LOW
