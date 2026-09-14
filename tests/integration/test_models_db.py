"""Integration tests: models against real Postgres 16.

Tests model creation, relationship traversal, evidence append-only invariant,
schema round-trips, and scoring determinism at the DB level.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign, CampaignStatus
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.content import AudienceInteraction, ContentItem, ContentType, InteractionType
from corp.core.models.creator import Creator, CreatorPlatformAccount, CreatorStatus
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember, ProblemObservation
from corp.core.models.intent import CommercialSignal, SignalLevel
from corp.core.models.niche import Niche, NicheAlias, NicheLifecycleStatus, NichePolicyClass
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.core.models.workflow import DecisionType, Gate, HumanDecision, ResearchRun
from corp.core.schemas.campaign import CampaignResponse
from corp.core.schemas.campaign_niche import CampaignNicheResponse
from corp.core.schemas.creator import CreatorResponse
from corp.core.schemas.evidence import EvidenceResponse
from corp.core.schemas.niche import NicheDetailResponse

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


# ---------- Campaign ----------


@pytest.mark.asyncio
async def test_create_campaign_with_defaults(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Q4 Creator Sweep")
    session.add(campaign)
    await session.flush()

    assert campaign.id is not None
    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.target_niche_count == 10
    assert campaign.initial_creators_per_niche == 10
    assert campaign.creator_min_followers == 10_000
    assert campaign.creator_max_followers == 200_000
    assert campaign.human_gate_capacity == 50
    assert campaign.created_at is not None
    assert campaign.started_at is None
    assert campaign.completed_at is None


@pytest.mark.asyncio
async def test_create_campaign_with_custom_config(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(
        name="Reef Aquarium Pilot",
        research_profile_version="v1",
        target_niche_count=5,
        initial_creators_per_niche=15,
        creator_min_followers=5_000,
        creator_max_followers=100_000,
        human_gate_capacity=25,
        status=CampaignStatus.ACTIVE,
    )
    session.add(campaign)
    await session.flush()

    assert campaign.target_niche_count == 5
    assert campaign.initial_creators_per_niche == 15
    assert campaign.creator_min_followers == 5_000
    assert campaign.creator_max_followers == 100_000
    assert campaign.human_gate_capacity == 25
    assert campaign.status == CampaignStatus.ACTIVE


@pytest.mark.asyncio
async def test_campaign_can_be_retrieved(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Home Espresso Pilot")
    session.add(campaign)
    await session.flush()
    campaign_id = campaign.id

    result = await session.execute(select(Campaign).where(Campaign.id == campaign_id))
    loaded = result.scalar_one()
    assert loaded.name == "Home Espresso Pilot"
    assert loaded.id == campaign_id


@pytest.mark.asyncio
async def test_campaign_schema_round_trip(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Sim Racing Pilot", target_niche_count=8)
    session.add(campaign)
    await session.flush()

    response = CampaignResponse.model_validate(campaign)
    assert response.name == "Sim Racing Pilot"
    assert response.target_niche_count == 8
    assert response.status == CampaignStatus.DRAFT


@pytest.mark.asyncio
async def test_creator_creation_unaffected_by_campaign_addition(clean_db: AsyncSession):
    """Slice 1 must not change existing creator behavior."""
    session = clean_db
    creator = await _create_creator(session, "Unaffected Creator")
    assert creator.status == CreatorStatus.DISCOVERED
    assert creator.id is not None


# ---------- Niche + NicheAlias ----------


@pytest.mark.asyncio
async def test_create_niche_with_defaults(clean_db: AsyncSession):
    session = clean_db
    niche = Niche(canonical_name="Home Espresso")
    session.add(niche)
    await session.flush()

    assert niche.id is not None
    assert niche.policy_class == NichePolicyClass.STANDARD
    assert niche.lifecycle_status == NicheLifecycleStatus.CANDIDATE
    assert niche.first_discovered_at is not None
    assert niche.last_researched_at is None
    assert niche.next_recheck_at is None


@pytest.mark.asyncio
async def test_niche_aliases_map_to_one_canonical_niche(clean_db: AsyncSession):
    session = clean_db
    niche = Niche(canonical_name="Home Espresso")
    session.add(niche)
    await session.flush()

    alias1 = NicheAlias(niche_id=niche.id, alias="home barista")
    alias2 = NicheAlias(niche_id=niche.id, alias="espresso hobbyist")
    session.add_all([alias1, alias2])
    await session.flush()

    await session.refresh(niche, ["aliases"])
    assert len(niche.aliases) == 2
    assert {a.alias for a in niche.aliases} == {"home barista", "espresso hobbyist"}
    assert all(a.niche_id == niche.id for a in niche.aliases)


@pytest.mark.asyncio
async def test_duplicate_canonical_name_case_insensitive_rejected(clean_db: AsyncSession):
    session = clean_db
    session.add(Niche(canonical_name="DIY Performance Tuning"))
    await session.flush()

    session.add(Niche(canonical_name="diy performance tuning"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_duplicate_alias_across_different_niches_rejected(clean_db: AsyncSession):
    session = clean_db
    niche_a = Niche(canonical_name="Home Espresso")
    niche_b = Niche(canonical_name="Sim Racing")
    session.add_all([niche_a, niche_b])
    await session.flush()

    session.add(NicheAlias(niche_id=niche_a.id, alias="hobby corner"))
    await session.flush()

    session.add(NicheAlias(niche_id=niche_b.id, alias="Hobby Corner"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_niche_lifecycle_and_restricted_policy_persist(clean_db: AsyncSession):
    session = clean_db
    niche = Niche(
        canonical_name="Home Supplement Stacking",
        policy_class=NichePolicyClass.RESTRICTED,
        lifecycle_status=NicheLifecycleStatus.ACTIVE,
    )
    session.add(niche)
    await session.flush()
    niche_id = niche.id

    result = await session.execute(select(Niche).where(Niche.id == niche_id))
    loaded = result.scalar_one()
    assert loaded.policy_class == NichePolicyClass.RESTRICTED
    assert loaded.lifecycle_status == NicheLifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_niche_schema_round_trip(clean_db: AsyncSession):
    session = clean_db
    niche = Niche(canonical_name="Reef Aquariums", parent_domain="Fish Keeping")
    session.add(niche)
    await session.flush()
    session.add(NicheAlias(niche_id=niche.id, alias="saltwater tank hobby"))
    await session.flush()
    await session.refresh(niche, ["aliases"])

    response = NicheDetailResponse.model_validate(niche)
    assert response.canonical_name == "Reef Aquariums"
    assert response.parent_domain == "Fish Keeping"
    assert len(response.aliases) == 1
    assert response.aliases[0].alias == "saltwater tank hobby"


@pytest.mark.asyncio
async def test_campaign_creation_unaffected_by_niche_addition(clean_db: AsyncSession):
    """Slice 2 must not change existing campaign (or earlier) behavior."""
    session = clean_db
    campaign = Campaign(name="Unaffected Campaign")
    session.add(campaign)
    await session.flush()
    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.id is not None


# ---------- CampaignNiche ----------


async def _create_campaign_and_niche(
    session: AsyncSession, campaign_name: str = "Q4 Sweep", niche_name: str = "Home Espresso"
) -> tuple[Campaign, Niche]:
    campaign = Campaign(name=campaign_name)
    niche = Niche(canonical_name=niche_name)
    session.add_all([campaign, niche])
    await session.flush()
    return campaign, niche


@pytest.mark.asyncio
async def test_create_campaign_niche_with_defaults(clean_db: AsyncSession):
    session = clean_db
    campaign, niche = await _create_campaign_and_niche(session)

    cn = CampaignNiche(campaign_id=campaign.id, niche_id=niche.id)
    session.add(cn)
    await session.flush()

    assert cn.id is not None
    assert cn.status == CampaignNicheStatus.DISCOVERED
    assert cn.selected is False
    assert cn.creator_count_observed == 0
    assert cn.qualification_score is None
    assert cn.confidence is None
    assert cn.research_completeness is None


@pytest.mark.asyncio
async def test_same_niche_appears_in_multiple_campaigns(clean_db: AsyncSession):
    session = clean_db
    niche = Niche(canonical_name="Reef Aquariums")
    campaign_a = Campaign(name="Spring Sweep")
    campaign_b = Campaign(name="Fall Sweep")
    session.add_all([niche, campaign_a, campaign_b])
    await session.flush()

    cn_a = CampaignNiche(campaign_id=campaign_a.id, niche_id=niche.id, discovery_rank=3)
    cn_b = CampaignNiche(campaign_id=campaign_b.id, niche_id=niche.id, discovery_rank=1)
    session.add_all([cn_a, cn_b])
    await session.flush()

    result = await session.execute(
        select(CampaignNiche).where(CampaignNiche.niche_id == niche.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert {r.campaign_id for r in rows} == {campaign_a.id, campaign_b.id}


@pytest.mark.asyncio
async def test_duplicate_campaign_niche_pair_rejected(clean_db: AsyncSession):
    session = clean_db
    campaign, niche = await _create_campaign_and_niche(session)

    session.add(CampaignNiche(campaign_id=campaign.id, niche_id=niche.id))
    await session.flush()

    session.add(CampaignNiche(campaign_id=campaign.id, niche_id=niche.id))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_campaign_niche_history_does_not_overwrite_canonical_niche(
    clean_db: AsyncSession,
):
    """Two campaigns score the same niche differently; the canonical Niche row
    and both CampaignNiche history rows must all remain independently intact."""
    session = clean_db
    niche = Niche(canonical_name="Sim Racing", description="Original description")
    campaign_a = Campaign(name="Weak Pass")
    campaign_b = Campaign(name="Strong Pass")
    session.add_all([niche, campaign_a, campaign_b])
    await session.flush()

    cn_weak = CampaignNiche(
        campaign_id=campaign_a.id,
        niche_id=niche.id,
        qualification_score=0.2,
        status=CampaignNicheStatus.REJECTED,
        rationale="Thin evidence in this pass",
    )
    cn_strong = CampaignNiche(
        campaign_id=campaign_b.id,
        niche_id=niche.id,
        qualification_score=0.9,
        status=CampaignNicheStatus.SELECTED,
        selected=True,
        rationale="Strong creator ecosystem this pass",
    )
    session.add_all([cn_weak, cn_strong])
    await session.flush()

    result = await session.execute(select(Niche).where(Niche.id == niche.id))
    loaded_niche = result.scalar_one()
    assert loaded_niche.description == "Original description"

    result = await session.execute(
        select(CampaignNiche).where(CampaignNiche.niche_id == niche.id)
    )
    rows = {r.campaign_id: r for r in result.scalars().all()}
    assert rows[campaign_a.id].qualification_score == 0.2
    assert rows[campaign_a.id].status == CampaignNicheStatus.REJECTED
    assert rows[campaign_b.id].qualification_score == 0.9
    assert rows[campaign_b.id].status == CampaignNicheStatus.SELECTED
    assert rows[campaign_b.id].selected is True


@pytest.mark.asyncio
async def test_campaign_niche_schema_round_trip(clean_db: AsyncSession):
    session = clean_db
    campaign, niche = await _create_campaign_and_niche(session)
    cn = CampaignNiche(
        campaign_id=campaign.id,
        niche_id=niche.id,
        discovery_rank=2,
        target_band_creator_count=14,
    )
    session.add(cn)
    await session.flush()

    response = CampaignNicheResponse.model_validate(cn)
    assert response.campaign_id == campaign.id
    assert response.niche_id == niche.id
    assert response.discovery_rank == 2
    assert response.target_band_creator_count == 14
    assert response.status == CampaignNicheStatus.DISCOVERED


@pytest.mark.asyncio
async def test_niche_creation_unaffected_by_campaign_niche_addition(clean_db: AsyncSession):
    """Slice 3 must not change existing niche (or earlier) behavior."""
    session = clean_db
    niche = Niche(canonical_name="Unaffected Niche")
    session.add(niche)
    await session.flush()
    assert niche.lifecycle_status == NicheLifecycleStatus.CANDIDATE
    assert niche.id is not None
