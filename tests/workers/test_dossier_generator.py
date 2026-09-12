"""Unit tests for dossier rendering — no DB, fixture data only."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from corp.core.models.competitive import CompetitorStrength, CompetitorType
from corp.core.models.intent import SignalLevel
from corp.core.models.scoring import ConfidenceBand


_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "corp" / "workers" / "dossier" / "templates"


class FakeCreator:
    name = "TestCreator"
    niche = "tech"
    discovery_source = "manual"
    status = "scored"


class FakeAccount:
    platform = "youtube"
    handle = "@testcreator"
    subscriber_count = 500_000


class FakeCreatorScore:
    aggregate_score = 0.72
    confidence_band = ConfidenceBand.HIGH
    rule_version = "scoring_v1"
    computed_hash = "abc123def456abc123def456abc123def456abc123def456abc123def456abcd"
    component_scores = {
        "audience_problem_frequency": 0.65,
        "recency_trend": 0.80,
        "commercial_intent_strength": 0.64,
        "evidence_depth": 0.55,
        "creator_reach": 0.81,
        "competition_saturation": 0.50,
    }


class FakeCluster:
    label = "Battery Issues"
    description = "Users report battery problems"
    frequency = 15


class FakeOppScore:
    aggregate_score = 0.68
    component_scores = {
        "audience_problem_frequency": 0.60,
        "recency_trend": 0.75,
        "commercial_intent_strength": 0.64,
        "evidence_depth": 0.50,
        "creator_reach": 0.81,
        "competition_saturation": 0.50,
    }


class FakeSignal:
    signal_level = SignalLevel.STRONG
    confidence = 0.85
    rationale = "Multiple comments ask about purchasing replacements"


class FakeObservation:
    text = "Where can I buy a battery replacement?"
    evidence_id = "ev-001"
    confidence = 0.9


class FakeCompetitor:
    name = "GenericBatteryCo replacement kit"
    competitor_type = CompetitorType.SUBSTITUTE
    strength = CompetitorStrength.MODERATE
    url = "https://example.com/kit"
    gap_notes = "Does not fit this device battery compartment without modification"


class FakeOpportunity:
    cluster = FakeCluster()
    score = FakeOppScore()
    signal = FakeSignal()
    observations = [FakeObservation(), FakeObservation()]
    competitors = []


class FakeSignalCtx:
    cluster_label = "Battery Issues"
    signal = FakeSignal()


class FakeDataCoverage:
    source_count = 2
    evidence_count = 25
    cluster_count = 3
    observation_count = 18
    competitor_count = 4


def _render_template(**kwargs) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("dossier.html.j2")
    return template.render(**kwargs)


async def test_render_full_dossier():
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[FakeAccount()],
        creator_score=FakeCreatorScore(),
        score_band="Strong opportunity",
        weights={"audience_problem_frequency": 0.25, "recency_trend": 0.15},
        opportunities=[FakeOpportunity()],
        signals=[FakeSignalCtx()],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "<!DOCTYPE html>" in html
    assert "TestCreator" in html
    assert "Battery Issues" in html
    assert "STRONG" in html
    assert "0.72" in html
    assert "Strong opportunity" in html
    assert "500,000" in html


async def test_render_no_clusters():
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=None,
        score_band="",
        weights={},
        opportunities=[],
        signals=[],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "<!DOCTYPE html>" in html
    assert "TestCreator" in html
    assert "No problem clusters" in html


async def test_render_no_signal():
    opp = FakeOpportunity()
    opp.signal = None
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=FakeCreatorScore(),
        score_band="Strong opportunity",
        weights={},
        opportunities=[opp],
        signals=[],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "NONE" in html
    assert "TestCreator" in html


async def test_evidence_references_present():
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=FakeCreatorScore(),
        score_band="Strong",
        weights={},
        opportunities=[FakeOpportunity()],
        signals=[FakeSignalCtx()],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "ev-001" in html
    assert "Where can I buy a battery replacement?" in html


async def test_score_breakdown_matches():
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=FakeCreatorScore(),
        score_band="Strong",
        weights={"audience_problem_frequency": 0.25},
        opportunities=[],
        signals=[],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "0.650" in html
    assert "0.800" in html
    assert "Audience Problem Frequency" in html


async def test_confidence_badge():
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=FakeCreatorScore(),
        score_band="Strong",
        weights={},
        opportunities=[],
        signals=[],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "badge-high" in html
    assert "HIGH" in html


async def test_stubs_present():
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=None,
        score_band="",
        weights={},
        opportunities=[],
        signals=[],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "Phase 5+" in html
    assert "Competitive" in html
    assert "Product Concepts" in html


async def test_competitive_landscape_with_data():
    opp = FakeOpportunity()
    opp.competitors = [FakeCompetitor()]
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=FakeCreatorScore(),
        score_band="Strong opportunity",
        weights={},
        opportunities=[opp],
        signals=[FakeSignalCtx()],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "GenericBatteryCo replacement kit" in html
    assert "SUBSTITUTE" in html
    assert "MODERATE" in html
    assert "Does not fit this device battery compartment without modification" in html
    assert "No competitive research recorded" not in html


async def test_competitive_landscape_empty():
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=FakeCreatorScore(),
        score_band="Strong opportunity",
        weights={},
        opportunities=[FakeOpportunity()],
        signals=[FakeSignalCtx()],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "No competitive research recorded yet" in html


async def test_data_coverage_section():
    html = _render_template(
        creator=FakeCreator(),
        platform_accounts=[],
        creator_score=None,
        score_band="",
        weights={},
        opportunities=[],
        signals=[],
        data_coverage=FakeDataCoverage(),
        generated_at="2025-01-15 10:30 UTC",
    )

    assert "Data Sources" in html
    assert "Total Evidence" in html
    assert "25" in html
