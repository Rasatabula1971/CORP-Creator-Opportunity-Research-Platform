"""Integration tests for ScoringPipeline against real Postgres."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.competitive import Competitor, CompetitorStrength, CompetitorType
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal, SignalLevel
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.scoring_pipeline import SCORING_RULE_VERSION, ScoringPipeline


async def _seed(session: AsyncSession) -> tuple[Creator, ProblemCluster]:
    creator = Creator(name="ScoreTest", niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()

    acct = CreatorPlatformAccount(
        creator_id=creator.id,
        platform="youtube",
        handle="@scoretest",
        subscriber_count=500_000,
    )
    session.add(acct)

    run = ResearchRun(
        creator_id=creator.id,
        status="completed",
        config_snapshot={},
        prompt_versions={},
        model_versions={},
    )
    session.add(run)
    await session.flush()

    cluster = ProblemCluster(
        label="Screen Issues",
        description="Users report screen problems",
        frequency=15,
        recency_score=0.8,
        evidence_strength=0.7,
        model_version="test",
    )
    session.add(cluster)
    await session.flush()

    for i in range(5):
        evidence = Evidence(
            source_type="comment",
            source_id=f"score_cmt_{i}",
            source_platform="youtube",
            raw_text=f"Screen problem #{i}",
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
            research_run_id=run.id,
            origin=EvidenceOrigin.OBSERVATION,
            evidence_type=EvidenceType.PROBLEM,
        )
        session.add(evidence)
        await session.flush()

        obs = ProblemObservation(
            evidence_id=evidence.id,
            text=f"Screen problem #{i}",
            category="problem",
            is_inferred=False,
            extraction_prompt_version="extract_v1",
            model_version="test",
            confidence=0.9,
        )
        session.add(obs)
        await session.flush()

        member = ProblemClusterMember(
            cluster_id=cluster.id,
            observation_id=obs.id,
            similarity_score=0.9,
        )
        session.add(member)

    await session.flush()

    signal_evidence = Evidence(
        source_type="intent_classification",
        source_id=cluster.id,
        source_platform="gemini",
        raw_text="Strong commercial intent",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        research_run_id=run.id,
        origin=EvidenceOrigin.INFERENCE,
        evidence_type=EvidenceType.PROBLEM,
    )
    session.add(signal_evidence)
    await session.flush()

    signal = CommercialSignal(
        problem_cluster_id=cluster.id,
        signal_level=SignalLevel.STRONG,
        evidence_id=signal_evidence.id,
        rationale="Strong buying intent",
        confidence=0.85,
        classification_model="test",
        prompt_version="intent_v1",
    )
    session.add(signal)
    await session.flush()

    return creator, cluster


@pytest.mark.asyncio
async def test_scoring_pipeline_creates_run(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed(session)
    pipeline = ScoringPipeline(session)

    run = await pipeline.run(creator.id)

    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.config_snapshot["pipeline"] == "scoring"


@pytest.mark.asyncio
async def test_scoring_pipeline_creates_opportunity_score(clean_db: AsyncSession):
    session = clean_db
    creator, cluster = await _seed(session)
    pipeline = ScoringPipeline(session)

    await pipeline.run(creator.id)

    result = await session.execute(
        select(OpportunityScore).where(
            OpportunityScore.problem_cluster_id == cluster.id
        )
    )
    opp = result.scalar_one()

    assert opp.creator_id == creator.id
    assert opp.aggregate_score > 0
    assert opp.computed_hash
    assert opp.rule_version == SCORING_RULE_VERSION
    assert "audience_problem_frequency" in opp.component_scores
    assert "commercial_intent_strength" in opp.component_scores


@pytest.mark.asyncio
async def test_scoring_pipeline_creates_creator_score(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed(session)
    pipeline = ScoringPipeline(session)

    await pipeline.run(creator.id)

    result = await session.execute(
        select(CreatorScore).where(CreatorScore.creator_id == creator.id)
    )
    cs = result.scalar_one()

    assert cs.aggregate_score > 0
    assert cs.computed_hash
    assert cs.rule_version == SCORING_RULE_VERSION
    assert cs.confidence_band in list(ConfidenceBand)


@pytest.mark.asyncio
async def test_scoring_pipeline_hash_determinism(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed(session)

    pipeline1 = ScoringPipeline(session)
    await pipeline1.run(creator.id)

    result1 = await session.execute(
        select(OpportunityScore).where(
            OpportunityScore.creator_id == creator.id
        )
    )
    opp1 = result1.scalar_one()
    hash1 = opp1.computed_hash
    components1 = opp1.component_scores

    pipeline2 = ScoringPipeline(session)
    await pipeline2.run(creator.id)

    result2 = await session.execute(
        select(OpportunityScore)
        .where(OpportunityScore.creator_id == creator.id)
        .where(OpportunityScore.id != opp1.id)
    )
    opp2 = result2.scalar_one()

    assert opp2.computed_hash == hash1
    assert opp2.component_scores == components1


@pytest.mark.asyncio
async def test_scoring_pipeline_no_clusters(clean_db: AsyncSession):
    session = clean_db
    creator = Creator(name="NoClusters", niche="test", discovery_source="manual")
    session.add(creator)
    await session.flush()

    pipeline = ScoringPipeline(session)
    run = await pipeline.run(creator.id)

    assert run.status == "completed"

    result = await session.execute(
        select(CreatorScore).where(CreatorScore.creator_id == creator.id)
    )
    cs = result.scalar_one()
    assert cs.aggregate_score == 0.0
    assert cs.confidence_band == ConfidenceBand.INSUFFICIENT


@pytest.mark.asyncio
async def test_scoring_pipeline_competition_saturation_neutral_without_competitors(
    clean_db: AsyncSession,
):
    session = clean_db
    creator, cluster = await _seed(session)
    pipeline = ScoringPipeline(session)

    await pipeline.run(creator.id)

    result = await session.execute(
        select(OpportunityScore).where(OpportunityScore.problem_cluster_id == cluster.id)
    )
    opp = result.scalar_one()
    assert opp.component_scores["competition_saturation"] == 0.5


@pytest.mark.asyncio
async def test_scoring_pipeline_competition_saturation_reflects_competitors(
    clean_db: AsyncSession,
):
    session = clean_db
    creator, cluster = await _seed(session)
    session.add_all([
        Competitor(
            problem_cluster_id=cluster.id,
            name="Incumbent A",
            competitor_type=CompetitorType.DIRECT,
            strength=CompetitorStrength.STRONG,
        ),
        Competitor(
            problem_cluster_id=cluster.id,
            name="Incumbent B",
            competitor_type=CompetitorType.SUBSTITUTE,
            strength=CompetitorStrength.MODERATE,
        ),
    ])
    await session.flush()

    pipeline = ScoringPipeline(session)
    await pipeline.run(creator.id)

    result = await session.execute(
        select(OpportunityScore).where(OpportunityScore.problem_cluster_id == cluster.id)
    )
    opp = result.scalar_one()
    # Post-integration merge: main's Competitor-list signal now feeds
    # `competitor_saturation` (not `competition_saturation`, which reads
    # commerce-overlap from creator-web pages instead).
    assert opp.component_scores["competitor_saturation"] < 0.5


@pytest.mark.asyncio
async def test_t21_evidence_type_counts_flow_from_niche_runs(clean_db: AsyncSession):
    """T21: niche-discovery evidence with evidence_type feeds the four new components."""
    session = clean_db
    from corp.core.models.niche import Niche

    niche = Niche(canonical_name="test-niche-scoring")
    session.add(niche)
    await session.flush()

    creator, cluster = await _seed(session)

    cn = CreatorNiche(creator_id=creator.id, niche_id=niche.id)
    session.add(cn)
    await session.flush()

    niche_run = ResearchRun(
        niche_id=niche.id,
        status="completed",
        run_type="niche_discovery",
        config_snapshot={},
        prompt_versions={},
        model_versions={},
    )
    session.add(niche_run)
    await session.flush()

    for et, count in [
        (EvidenceType.TREND, 5),
        (EvidenceType.SEARCH_INTENT, 3),
        (EvidenceType.TRANSACTION, 4),
        (EvidenceType.DISSATISFACTION, 6),
        (EvidenceType.SOLUTION, 2),
    ]:
        for i in range(count):
            ev = Evidence(
                source_type="adapter",
                source_id=f"{et.value}_{i}",
                source_platform="test",
                raw_text=f"{et.value} evidence #{i}",
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.COMPLIANT,
                research_run_id=niche_run.id,
                evidence_type=et,
                origin=EvidenceOrigin.OBSERVATION,
            )
            session.add(ev)
    await session.flush()

    pipeline = ScoringPipeline(session)
    await pipeline.run(creator.id)

    result = await session.execute(
        select(OpportunityScore).where(OpportunityScore.problem_cluster_id == cluster.id)
    )
    opp = result.scalar_one()

    assert len(opp.component_scores) == 14
    assert opp.component_scores["external_demand_strength"] > 0.0
    assert opp.component_scores["purchase_intent"] > 0.0
    assert opp.component_scores["audience_dissatisfaction"] > 0.0
    assert opp.component_scores["solution_saturation"] != 0.5


@pytest.mark.asyncio
async def test_t21_no_niche_evidence_gives_neutral_components(clean_db: AsyncSession):
    """Without niche-discovery evidence, the four T7 components return neutral/zero."""
    session = clean_db
    creator, cluster = await _seed(session)
    pipeline = ScoringPipeline(session)

    await pipeline.run(creator.id)

    result = await session.execute(
        select(OpportunityScore).where(OpportunityScore.problem_cluster_id == cluster.id)
    )
    opp = result.scalar_one()

    assert opp.component_scores["external_demand_strength"] == 0.0
    assert opp.component_scores["solution_saturation"] == 0.5
    assert opp.component_scores["purchase_intent"] == 0.0
    assert opp.component_scores["audience_dissatisfaction"] == 0.0


@pytest.mark.asyncio
async def test_scoring_pipeline_bad_rules_raises(clean_db: AsyncSession):
    session = clean_db
    with pytest.raises(FileNotFoundError):
        ScoringPipeline(session, rules_path="nonexistent.yaml")
