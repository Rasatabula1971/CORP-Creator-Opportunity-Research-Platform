"""Integration tests: models against real Postgres 16.

Tests model creation, relationship traversal, evidence append-only invariant,
schema round-trips, and scoring determinism at the DB level.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem, ContentType, InteractionType
from corp.core.models.creator import Creator, CreatorPlatformAccount, CreatorStatus
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember, ProblemObservation
from corp.core.models.intent import CommercialSignal, SignalLevel
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.core.models.workflow import DecisionType, Gate, HumanDecision, ResearchRun
from corp.core.schemas.creator import CreatorResponse, PlatformAccountResponse
from corp.core.schemas.evidence import EvidenceResponse


# ---------- Creator + PlatformAccount ----------


async def _create_creator(session: AsyncSession, name: str = "MKBHD") -> Creator:
    creator = Creator(name=name, niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()
    return creator


@pytest.mark.asyncio
async def test_create_creator(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)
    assert creator.id is not None
    assert creator.status == CreatorStatus.DISCOVERED
    assert creator.created_at is not None


@pytest.mark.asyncio
async def test_creator_platform_account_relationship(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)
    account = CreatorPlatformAccount(
        creator_id=creator.id, platform="youtube", handle="@mkbhd", external_id="UC123"
    )
    session.add(account)
    await session.flush()

    result = await session.execute(
        select(Creator).where(Creator.id == creator.id)
    )
    loaded = result.scalar_one()
    await session.refresh(loaded, ["platform_accounts"])
    assert len(loaded.platform_accounts) == 1
    assert loaded.platform_accounts[0].handle == "@mkbhd"


@pytest.mark.asyncio
async def test_creator_schema_round_trip(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)
    response = CreatorResponse.model_validate(creator)
    assert response.name == "MKBHD"
    assert response.status == CreatorStatus.DISCOVERED


# ---------- Content + Interactions ----------


@pytest.mark.asyncio
async def test_content_item_with_interactions(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)

    video = ContentItem(
        creator_id=creator.id,
        platform="youtube",
        external_id="vid_001",
        title="iPhone Review",
        content_type=ContentType.VIDEO,
    )
    session.add(video)
    await session.flush()

    comment = AudienceInteraction(
        content_item_id=video.id,
        external_id="cmt_001",
        text="Great review! Where can I buy the case you showed?",
        author_handle="viewer1",
        interaction_type=InteractionType.COMMENT,
    )
    session.add(comment)
    await session.flush()

    await session.refresh(video, ["interactions"])
    assert len(video.interactions) == 1
    assert "Where can I buy" in video.interactions[0].text


# ---------- Evidence (append-only invariant) ----------


async def _create_evidence(session: AsyncSession) -> Evidence:
    evidence = Evidence(
        source_type="comment",
        source_id="cmt_001",
        source_platform="youtube",
        raw_text="I wish there was a better case for this phone",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
    )
    session.add(evidence)
    await session.flush()
    return evidence


@pytest.mark.asyncio
async def test_create_evidence(clean_db: AsyncSession):
    session = clean_db
    evidence = await _create_evidence(session)
    assert evidence.id is not None
    assert evidence.collected_at is not None


@pytest.mark.asyncio
async def test_evidence_schema_round_trip(clean_db: AsyncSession):
    session = clean_db
    evidence = await _create_evidence(session)
    response = EvidenceResponse.model_validate(evidence)
    assert response.access_method == AccessMethod.OFFICIAL
    assert response.compliance_status == ComplianceStatus.COMPLIANT


@pytest.mark.asyncio
async def test_evidence_blocks_update(clean_db: AsyncSession):
    session = clean_db
    evidence = await _create_evidence(session)
    with pytest.raises(Exception, match="append-only"):
        await session.execute(
            text("UPDATE evidence SET raw_text = 'modified' WHERE id = :id"),
            {"id": evidence.id},
        )


@pytest.mark.asyncio
async def test_evidence_blocks_delete(clean_db: AsyncSession):
    session = clean_db
    evidence = await _create_evidence(session)
    with pytest.raises(Exception, match="append-only"):
        await session.execute(
            text("DELETE FROM evidence WHERE id = :id"),
            {"id": evidence.id},
        )


# ---------- ProblemObservation + Cluster ----------


@pytest.mark.asyncio
async def test_observation_linked_to_evidence(clean_db: AsyncSession):
    session = clean_db
    evidence = await _create_evidence(session)
    obs = ProblemObservation(
        evidence_id=evidence.id,
        text="Users want a better phone case",
        category="product_need",
        is_inferred=False,
        extraction_prompt_version="v1.0",
        model_version="gemini-1.5-flash",
    )
    session.add(obs)
    await session.flush()
    assert obs.id is not None
    assert obs.evidence_id == evidence.id


@pytest.mark.asyncio
async def test_cluster_with_members(clean_db: AsyncSession):
    session = clean_db
    evidence = await _create_evidence(session)
    obs1 = ProblemObservation(
        evidence_id=evidence.id,
        text="Need a better case",
        is_inferred=False,
        extraction_prompt_version="v1.0",
        model_version="gemini-1.5-flash",
    )
    obs2 = ProblemObservation(
        evidence_id=evidence.id,
        text="Looking for durable phone protection",
        is_inferred=False,
        extraction_prompt_version="v1.0",
        model_version="gemini-1.5-flash",
    )
    session.add_all([obs1, obs2])
    await session.flush()

    cluster = ProblemCluster(label="Phone case demand", frequency=2, evidence_strength=0.8)
    session.add(cluster)
    await session.flush()

    m1 = ProblemClusterMember(cluster_id=cluster.id, observation_id=obs1.id, similarity_score=0.95)
    m2 = ProblemClusterMember(cluster_id=cluster.id, observation_id=obs2.id, similarity_score=0.88)
    session.add_all([m1, m2])
    await session.flush()

    await session.refresh(cluster, ["members"])
    assert len(cluster.members) == 2


# ---------- CommercialSignal ----------


@pytest.mark.asyncio
async def test_commercial_signal(clean_db: AsyncSession):
    session = clean_db
    evidence = await _create_evidence(session)
    cluster = ProblemCluster(label="Case demand", frequency=5, evidence_strength=0.9)
    session.add(cluster)
    await session.flush()

    signal = CommercialSignal(
        problem_cluster_id=cluster.id,
        signal_level=SignalLevel.STRONG,
        evidence_id=evidence.id,
        rationale="Direct purchase intent in comments",
        classification_model="gemini-1.5-flash",
        prompt_version="v1.0",
    )
    session.add(signal)
    await session.flush()
    assert signal.signal_level == SignalLevel.STRONG


# ---------- Scoring ----------


@pytest.mark.asyncio
async def test_creator_score_determinism(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)

    from corp.core.scoring.engine import compute_hash, compute_score

    components = {"frequency": 0.8, "recency": 0.6, "intent": 0.9}
    weights = {"frequency": 0.25, "recency": 0.15, "intent": 0.20}
    agg = compute_score(components, weights)
    h = compute_hash(components, "v1.0.0")

    score = CreatorScore(
        creator_id=creator.id,
        component_scores=components,
        aggregate_score=agg,
        computed_hash=h,
        confidence_band=ConfidenceBand.HIGH,
        rule_version="v1.0.0",
        model_version="gemini-1.5-flash",
    )
    session.add(score)
    await session.flush()

    h2 = compute_hash(components, "v1.0.0")
    assert score.computed_hash == h2


@pytest.mark.asyncio
async def test_opportunity_score_split(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)
    cluster = ProblemCluster(label="Test", frequency=1, evidence_strength=0.5)
    session.add(cluster)
    await session.flush()

    opp = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores={"frequency": 0.7},
        aggregate_score=0.7,
        computed_hash="abc123",
        confidence_band=ConfidenceBand.MEDIUM,
        rule_version="v1.0.0",
        model_version="gemini-1.5-flash",
    )
    session.add(opp)
    await session.flush()
    assert opp.problem_cluster_id == cluster.id


# ---------- Workflow: HumanDecision + ResearchRun ----------


@pytest.mark.asyncio
async def test_human_decision_append_only(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)

    d1 = HumanDecision(
        creator_id=creator.id,
        decision=DecisionType.WATCH,
        gate=Gate.GATE_A,
        rationale="Need more data",
    )
    session.add(d1)
    await session.flush()

    d2 = HumanDecision(
        creator_id=creator.id,
        decision=DecisionType.APPROVE,
        gate=Gate.GATE_A,
        rationale="Dossier is strong, proceed",
    )
    session.add(d2)
    await session.flush()

    result = await session.execute(
        select(HumanDecision).where(HumanDecision.creator_id == creator.id)
    )
    decisions = result.scalars().all()
    assert len(decisions) == 2


@pytest.mark.asyncio
async def test_research_run(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)

    run = ResearchRun(
        creator_id=creator.id,
        status="running",
        config_snapshot={"youtube_max_videos": 50},
        prompt_versions={"extraction": "v1.0", "intent": "v1.0"},
        model_versions={"extraction": "gemini-1.5-flash"},
    )
    session.add(run)
    await session.flush()
    assert run.id is not None
    assert run.prompt_versions["extraction"] == "v1.0"


# ---------- Full chain: Creator → Content → Interaction → Evidence → Observation ----------


@pytest.mark.asyncio
async def test_full_evidence_chain(clean_db: AsyncSession):
    """End-to-end: a comment becomes an evidence-backed observation."""
    session = clean_db
    creator = await _create_creator(session, "LTT")
    video = ContentItem(
        creator_id=creator.id,
        platform="youtube",
        external_id="vid_ltt_001",
        title="GPU Review",
        content_type=ContentType.VIDEO,
    )
    session.add(video)
    await session.flush()

    comment = AudienceInteraction(
        content_item_id=video.id,
        external_id="cmt_ltt_001",
        text="I wish there was a budget GPU that doesn't overheat",
        interaction_type=InteractionType.COMMENT,
    )
    session.add(comment)
    await session.flush()

    evidence = Evidence(
        source_type="comment",
        source_id=comment.external_id,
        source_platform="youtube",
        raw_text=comment.text,
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
    )
    session.add(evidence)
    await session.flush()

    obs = ProblemObservation(
        evidence_id=evidence.id,
        text="Users want budget GPUs that don't overheat",
        category="product_need",
        is_inferred=False,
        extraction_prompt_version="v1.0",
        model_version="gemini-1.5-flash",
    )
    session.add(obs)
    await session.flush()

    assert obs.evidence_id == evidence.id
    assert evidence.source_id == comment.external_id
    assert comment.content_item_id == video.id
    assert video.creator_id == creator.id
