"""Integration tests for DossierGenerator against real Postgres."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.competitive import Competitor, CompetitorStrength, CompetitorType
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal, SignalLevel
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.workers.dossier.generator import DossierGenerator


async def _seed_full(session: AsyncSession) -> Creator:
    """Seed a creator with clusters, signals, and scores — full pipeline output."""
    creator = Creator(name="DossierTest", niche="fitness", discovery_source="manual")
    session.add(creator)
    await session.flush()

    acct = CreatorPlatformAccount(
        creator_id=creator.id,
        platform="youtube",
        handle="@dossiertest",
        subscriber_count=250_000,
    )
    session.add(acct)

    run = ResearchRun(
        creator_id=creator.id,
        status="completed",
        config_snapshot={"pipeline": "scoring"},
        prompt_versions={},
        model_versions={},
    )
    session.add(run)
    await session.flush()

    cluster = ProblemCluster(
        label="Protein Timing",
        description="Audience confused about protein timing",
        frequency=20,
        recency_score=0.9,
        evidence_strength=0.8,
        model_version="test",
    )
    session.add(cluster)
    await session.flush()

    for i in range(4):
        ev = Evidence(
            source_type="comment",
            source_id=f"dos_cmt_{i}",
            source_platform="youtube",
            raw_text=f"When should I take protein? #{i}",
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
            research_run_id=run.id,
        )
        session.add(ev)
        await session.flush()

        obs = ProblemObservation(
            evidence_id=ev.id,
            text=f"When should I take protein? #{i}",
            category="question",
            is_inferred=False,
            extraction_prompt_version="extract_v1",
            model_version="test",
            confidence=0.88,
        )
        session.add(obs)
        await session.flush()

        member = ProblemClusterMember(
            cluster_id=cluster.id,
            observation_id=obs.id,
            similarity_score=0.92,
        )
        session.add(member)

    await session.flush()

    signal_ev = Evidence(
        source_type="intent_classification",
        source_id=cluster.id,
        source_platform="gemini",
        raw_text="Strong buying intent for protein products",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        research_run_id=run.id,
    )
    session.add(signal_ev)
    await session.flush()

    signal = CommercialSignal(
        problem_cluster_id=cluster.id,
        signal_level=SignalLevel.STRONG,
        evidence_id=signal_ev.id,
        rationale="Users asking where to buy protein supplements",
        confidence=0.88,
        classification_model="test",
        prompt_version="intent_v1",
    )
    session.add(signal)
    await session.flush()

    opp_components = {
        "audience_problem_frequency": 0.70,
        "recency_trend": 0.90,
        "commercial_intent_strength": 0.64,
        "evidence_depth": 0.50,
        "creator_reach": 0.77,
        "competition_saturation": 0.50,
    }
    opp_score = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores=opp_components,
        aggregate_score=0.68,
        computed_hash="a" * 64,
        confidence_band=ConfidenceBand.MEDIUM,
        rule_version="scoring_v1",
        model_version="deterministic",
        research_run_id=run.id,
    )
    session.add(opp_score)

    creator_components = dict(opp_components)
    creator_score = CreatorScore(
        creator_id=creator.id,
        component_scores=creator_components,
        aggregate_score=0.68,
        computed_hash="b" * 64,
        confidence_band=ConfidenceBand.MEDIUM,
        rule_version="scoring_v1",
        model_version="deterministic",
        research_run_id=run.id,
    )
    session.add(creator_score)

    competitor = Competitor(
        problem_cluster_id=cluster.id,
        name="BulkGains Protein Timer app",
        competitor_type=CompetitorType.SUBSTITUTE,
        strength=CompetitorStrength.WEAK,
        gap_notes="Only supports whey, not plant-based protein",
    )
    session.add(competitor)
    await session.flush()

    return creator


@pytest.mark.asyncio
async def test_dossier_generates_html(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed_full(session)

    gen = DossierGenerator(session)
    html = await gen.generate(creator.id)

    assert "<!DOCTYPE html>" in html
    assert "DossierTest" in html
    assert "Protein Timing" in html


@pytest.mark.asyncio
async def test_dossier_contains_scores(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed_full(session)

    gen = DossierGenerator(session)
    html = await gen.generate(creator.id)

    assert "0.68" in html
    assert "scoring_v1" in html
    assert "MEDIUM" in html


@pytest.mark.asyncio
async def test_dossier_contains_evidence(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed_full(session)

    gen = DossierGenerator(session)
    html = await gen.generate(creator.id)

    assert "When should I take protein?" in html
    assert "STRONG" in html


@pytest.mark.asyncio
async def test_dossier_data_coverage(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed_full(session)

    gen = DossierGenerator(session)
    data = await gen.generate_data(creator.id)

    assert data.data_coverage.cluster_count == 1
    assert data.data_coverage.observation_count == 4
    assert data.data_coverage.source_count >= 1
    assert data.data_coverage.competitor_count == 1


@pytest.mark.asyncio
async def test_dossier_contains_competitors(clean_db: AsyncSession):
    session = clean_db
    creator = await _seed_full(session)

    gen = DossierGenerator(session)
    html = await gen.generate(creator.id)

    assert "BulkGains Protein Timer app" in html
    assert "Only supports whey, not plant-based protein" in html
    assert "No competitive research recorded" not in html


@pytest.mark.asyncio
async def test_dossier_empty_creator(clean_db: AsyncSession):
    session = clean_db
    creator = Creator(name="EmptyCreator", niche="test", discovery_source="manual")
    session.add(creator)
    await session.flush()

    gen = DossierGenerator(session)
    html = await gen.generate(creator.id)

    assert "EmptyCreator" in html
    assert "No problem clusters" in html


@pytest.mark.asyncio
async def test_dossier_invalid_creator(clean_db: AsyncSession):
    session = clean_db
    gen = DossierGenerator(session)

    with pytest.raises(ValueError, match="Creator not found"):
        await gen.generate("nonexistent-id")
