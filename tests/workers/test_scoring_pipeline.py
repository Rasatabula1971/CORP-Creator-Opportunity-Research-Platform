"""Unit tests for ScoringPipeline configuration plumbing — no database."""

from corp.core.models.evidence import EvidenceType
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


# The relevance filter only credits a cluster with evidence whose text
# overlaps the cluster's own tokens (see _relevant_evidence_count), so
# fixtures built from raw counts need evidence text the mocked cluster
# context will actually match.
_CLUSTER_TOKENS: frozenset[str] = frozenset({"widget", "topic"})


def _creator_context(
    evidence_type_counts: dict[str, int] | None = None,
) -> CreatorContext:
    return CreatorContext(
        subscriber_count=1000,
        audience_platforms=["youtube"],
        creator_observation_tokens=[],
        commerce_page_tokens=[],
        commerce_signal_count=0,
        monetisation={},
        engagement_rate_by_platform={},
        follower_growth=None,
        market_evidence_tokens={
            et: [_CLUSTER_TOKENS] * count for et, count in (evidence_type_counts or {}).items()
        },
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


def _make_pipe_and_helpers(monkeypatch):
    """Shared setup for T21 scoring-integration tests."""

    async def _none(*args, **kwargs):
        return None

    async def _cluster_ctx(cluster):
        return ClusterContext(
            member_count=4,
            platforms={"youtube"},
            compliant_platforms={"youtube"},
            text_tokens=_CLUSTER_TOKENS,
        )

    async def _strengths(cluster_id):
        return []

    monkeypatch.setattr(
        scoring_pipeline, "compute_confidence_band", lambda **kw: ConfidenceBand.LOW
    )
    monkeypatch.setattr(scoring_pipeline, "mirror_scores", _none)

    pipe = ScoringPipeline(FakeSession())  # type: ignore[arg-type]
    pipe._get_signal = _none  # type: ignore[method-assign]
    pipe._load_cluster_context = _cluster_ctx  # type: ignore[method-assign]
    pipe._get_competitor_strengths = _strengths  # type: ignore[method-assign]
    pipe._previous_frequency = _none  # type: ignore[method-assign]
    return pipe


async def test_t21_all_fourteen_components_present(monkeypatch):
    pipe = _make_pipe_and_helpers(monkeypatch)
    ctx = _creator_context(evidence_type_counts={
        EvidenceType.TREND.value: 5,
        EvidenceType.SEARCH_INTENT.value: 8,
        EvidenceType.SOLUTION.value: 3,
        EvidenceType.TRANSACTION.value: 10,
        EvidenceType.DISSATISFACTION.value: 6,
    })
    cluster = ProblemCluster(id="c-1", label="x", frequency=3, recency_score=0.5)
    opp = await pipe._score_opportunity(cluster, "creator-1", ctx, "run-1")

    assert len(opp.component_scores) == 14
    for key in (
        "external_demand_strength",
        "solution_saturation",
        "purchase_intent",
        "audience_dissatisfaction",
    ):
        assert key in opp.component_scores


async def test_t21_evidence_counts_feed_nonzero_scores(monkeypatch):
    pipe = _make_pipe_and_helpers(monkeypatch)
    ctx = _creator_context(evidence_type_counts={
        EvidenceType.TREND.value: 10,
        EvidenceType.SEARCH_INTENT.value: 10,
        EvidenceType.TRANSACTION.value: 5,
        EvidenceType.DISSATISFACTION.value: 5,
    })
    cluster = ProblemCluster(id="c-1", label="x", frequency=3, recency_score=0.5)
    opp = await pipe._score_opportunity(cluster, "creator-1", ctx, "run-1")

    assert opp.component_scores["external_demand_strength"] > 0.0
    assert opp.component_scores["purchase_intent"] > 0.0
    assert opp.component_scores["audience_dissatisfaction"] > 0.0


async def test_t21_zero_evidence_gives_neutral_or_zero(monkeypatch):
    pipe = _make_pipe_and_helpers(monkeypatch)
    ctx = _creator_context(evidence_type_counts={})
    cluster = ProblemCluster(id="c-1", label="x", frequency=3, recency_score=0.5)
    opp = await pipe._score_opportunity(cluster, "creator-1", ctx, "run-1")

    assert opp.component_scores["external_demand_strength"] == 0.0
    assert opp.component_scores["solution_saturation"] == 0.5
    assert opp.component_scores["purchase_intent"] == 0.0
    assert opp.component_scores["audience_dissatisfaction"] == 0.0


async def test_t21_aggregate_uses_all_fourteen_weights(monkeypatch):
    pipe = _make_pipe_and_helpers(monkeypatch)
    ctx = _creator_context(evidence_type_counts={
        EvidenceType.TREND.value: 5,
        EvidenceType.SEARCH_INTENT.value: 5,
        EvidenceType.SOLUTION.value: 5,
        EvidenceType.TRANSACTION.value: 5,
        EvidenceType.DISSATISFACTION.value: 5,
    })
    cluster = ProblemCluster(id="c-1", label="x", frequency=10, recency_score=0.8)
    opp = await pipe._score_opportunity(cluster, "creator-1", ctx, "run-1")

    weights = load_scoring_rules("rules/scoring.yaml")["weights"]
    total_weight = sum(weights.get(k, 0.0) for k in opp.component_scores)
    assert abs(total_weight - 1.0) < 0.001
