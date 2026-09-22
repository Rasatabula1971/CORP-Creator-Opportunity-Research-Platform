"""Integration tests for DossierGenerator.generate_and_persist (CORP1
Stage 5, T6) against real Postgres."""


import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.creator import Creator
from corp.core.models.dossier import Dossier, DossierEvidence
from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember, ProblemObservation
from corp.core.models.niche import Niche
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateEvidence,
    NicheCandidateStatus,
)
from corp.core.models.product_idea import (
    ProductIdea,
    ProductIdeaComplexity,
    ProductIdeaEvidence,
    ProductIdeaType,
)
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun
from corp.workers.dossier.generator import DossierGenerator

RULES_PATH = "rules/scoring.yaml"


async def _make_creator(session: AsyncSession) -> Creator:
    creator = Creator(name="Coffee Creator", niche="home espresso", discovery_source="manual")
    session.add(creator)
    await session.flush()
    return creator


async def _make_niche(
    session: AsyncSession, name: str, parent_niche_id: str | None = None, depth: int = 0
) -> Niche:
    niche = Niche(canonical_name=name, parent_niche_id=parent_niche_id, depth=depth)
    session.add(niche)
    await session.flush()
    return niche


async def _make_run(session: AsyncSession, creator_id: str) -> ResearchRun:
    run = ResearchRun(creator_id=creator_id, status="completed")
    session.add(run)
    await session.flush()
    return run


async def _make_evidence(
    session: AsyncSession, run_id: str | None, text: str = "evidence text"
) -> Evidence:
    evidence = Evidence(
        source_type="comment",
        source_id=f"cmt_{text[:20]}",
        source_platform="youtube",
        raw_text=text,
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
        research_run_id=run_id,
        origin=EvidenceOrigin.OBSERVATION,
        evidence_type=EvidenceType.PROBLEM,
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def _make_scored_opportunity(
    session: AsyncSession,
    creator: Creator,
    run: ResearchRun,
    *,
    aggregate_score: float = 0.75,
    confidence_band: ConfidenceBand = ConfidenceBand.HIGH,
    label: str = "Grinder confusion",
    with_creator_score: bool = True,
) -> tuple[ProblemCluster, OpportunityScore, Evidence]:
    cluster = ProblemCluster(
        creator_id=creator.id, label=label, frequency=3, evidence_strength=0.8
    )
    session.add(cluster)
    await session.flush()

    evidence = await _make_evidence(session, run.id, "I wish there was a grinder chart")
    obs = ProblemObservation(
        evidence_id=evidence.id,
        text=evidence.raw_text,
        is_inferred=False,
        extraction_prompt_version="v1.0",
        model_version="fixture",
    )
    session.add(obs)
    await session.flush()
    session.add(
        ProblemClusterMember(cluster_id=cluster.id, observation_id=obs.id, similarity_score=0.9)
    )
    await session.flush()

    if with_creator_score:
        # One active CreatorScore per creator (partial unique index).
        session.add(
            CreatorScore(
                creator_id=creator.id,
                component_scores={"frequency": aggregate_score},
                aggregate_score=aggregate_score,
                computed_hash="hash1",
                confidence_band=confidence_band,
                rule_version="v1.0.0",
                model_version="fixture",
            )
        )
    opp = OpportunityScore(
        creator_id=creator.id,
        problem_cluster_id=cluster.id,
        component_scores={"frequency": aggregate_score},
        aggregate_score=aggregate_score,
        computed_hash="hash2",
        confidence_band=confidence_band,
        rule_version="v1.0.0",
        model_version="fixture",
        research_run_id=run.id,
    )
    session.add(opp)
    await session.commit()
    return cluster, opp, evidence


# ---------- Basic persistence ----------


@pytest.mark.asyncio
async def test_persists_dossier_row(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    run = await _make_run(session, creator.id)
    _, opp, _ = await _make_scored_opportunity(session, creator, run)

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    assert dossier.creator_id == creator.id
    assert dossier.niche_id == niche.id
    assert dossier.opportunity_score_id == opp.id
    assert dossier.status.value == "pending_review"
    assert dossier.content["score_band"]
    assert len(dossier.content["opportunities"]) == 1


# ---------- Stage 4 acceptance test: evidence trail traceable to a real ResearchRun ----------


@pytest.mark.asyncio
async def test_evidence_trail_only_contains_rows_with_a_research_run(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    run = await _make_run(session, creator.id)
    await _make_scored_opportunity(session, creator, run)

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    links = (
        await session.execute(
            select(DossierEvidence).where(DossierEvidence.dossier_id == dossier.id)
        )
    ).scalars().all()
    assert len(links) >= 1
    for link in links:
        evidence = await session.get(Evidence, link.evidence_id)
        assert evidence is not None
        assert evidence.research_run_id is not None


@pytest.mark.asyncio
async def test_evidence_without_research_run_excluded_from_trail(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    run = await _make_run(session, creator.id)
    cluster, opp, _ = await _make_scored_opportunity(session, creator, run)

    # A second observation on the same cluster whose evidence has no
    # research_run_id -- must never end up in the persisted trail.
    orphan_evidence = await _make_evidence(session, None, "orphan comment, no run")
    orphan_obs = ProblemObservation(
        evidence_id=orphan_evidence.id,
        text=orphan_evidence.raw_text,
        is_inferred=False,
        extraction_prompt_version="v1.0",
        model_version="fixture",
    )
    session.add(orphan_obs)
    await session.flush()
    session.add(
        ProblemClusterMember(
            cluster_id=cluster.id, observation_id=orphan_obs.id, similarity_score=0.5
        )
    )
    await session.commit()

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    linked_evidence_ids = {
        link.evidence_id
        for link in (
            await session.execute(
                select(DossierEvidence).where(DossierEvidence.dossier_id == dossier.id)
            )
        ).scalars().all()
    }
    assert orphan_evidence.id not in linked_evidence_ids


# ---------- niche_path ----------


@pytest.mark.asyncio
async def test_niche_path_walks_parent_chain_root_to_leaf(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    root = await _make_niche(session, "Automotive", depth=0)
    child = await _make_niche(session, "Track Builds", parent_niche_id=root.id, depth=1)
    leaf = await _make_niche(session, "Suspension", parent_niche_id=child.id, depth=2)
    run = await _make_run(session, creator.id)
    await _make_scored_opportunity(session, creator, run)

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, leaf.id)
    await session.commit()

    path = dossier.content["niche_path"]
    assert [p["canonical_name"] for p in path] == ["Automotive", "Track Builds", "Suspension"]
    assert [p["depth"] for p in path] == [0, 1, 2]


# ---------- Product ideas ----------


@pytest.mark.asyncio
async def test_product_ideas_included_in_content(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    run = await _make_run(session, creator.id)
    await _make_scored_opportunity(session, creator, run)

    cluster_result = await session.execute(
        select(ProblemCluster).where(ProblemCluster.creator_id == creator.id)
    )
    cluster_id = cluster_result.scalar_one().id
    idea = ProductIdea(
        creator_id=creator.id,
        problem_cluster_id=cluster_id,
        title="Grinder Comparison Chart",
        description="A chart comparing grinders",
        idea_type=ProductIdeaType.TEMPLATE,
        complexity=ProductIdeaComplexity.LOW,
        price_min=19,
        price_max=39,
        fit_rationale="Fits the espresso niche",
        evidence_terms=["grinder"],
        evidence_count=1,
        generation_prompt_version="test",
        generation_model_version="test",
    )
    session.add(idea)
    await session.flush()
    idea_evidence = await _make_evidence(session, run.id, "grinder recommendation post")
    session.add(ProductIdeaEvidence(product_idea_id=idea.id, evidence_id=idea_evidence.id))
    await session.commit()

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    assert len(dossier.content["product_ideas"]) == 1
    assert dossier.content["product_ideas"][0]["title"] == "Grinder Comparison Chart"

    links = (
        await session.execute(
            select(DossierEvidence).where(DossierEvidence.dossier_id == dossier.id)
        )
    ).scalars().all()
    assert idea_evidence.id in {link.evidence_id for link in links}


# ---------- Recommendation ----------


@pytest.mark.asyncio
async def test_recommendation_approve_for_strong_score_and_confidence(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    run = await _make_run(session, creator.id)
    await _make_scored_opportunity(
        session, creator, run, aggregate_score=0.90, confidence_band=ConfidenceBand.HIGH
    )

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    assert dossier.content["recommendation"]["suggested_action"] == "approve"


@pytest.mark.asyncio
async def test_recommendation_research_more_for_insufficient_confidence(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    run = await _make_run(session, creator.id)
    await _make_scored_opportunity(
        session, creator, run, aggregate_score=0.90, confidence_band=ConfidenceBand.INSUFFICIENT
    )

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    assert dossier.content["recommendation"]["suggested_action"] == "research_more"


@pytest.mark.asyncio
async def test_recommendation_reject_for_weak_score(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    run = await _make_run(session, creator.id)
    await _make_scored_opportunity(
        session, creator, run, aggregate_score=0.10, confidence_band=ConfidenceBand.LOW
    )

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    assert dossier.content["recommendation"]["suggested_action"] == "reject"


# ---------- Supersession ----------


@pytest.mark.asyncio
async def test_rerun_supersedes_prior_dossier(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    run = await _make_run(session, creator.id)
    await _make_scored_opportunity(session, creator, run)

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    first = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    second = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    await session.refresh(first)
    assert first.superseded_at is not None
    assert second.superseded_at is None

    all_dossiers = (
        await session.execute(select(Dossier).where(Dossier.creator_id == creator.id))
    ).scalars().all()
    assert len(all_dossiers) == 2  # never deleted


# ---------- Edge cases ----------


@pytest.mark.asyncio
async def test_niche_scoping_picks_niche_relevant_opportunity(clean_db: AsyncSession):
    """A multi-niche creator's dossier should reference the top opportunity
    whose evidence traces to THIS niche, not the globally highest score."""
    session = clean_db
    creator = await _make_creator(session)
    niche_a = await _make_niche(session, "Home Espresso")
    niche_b = await _make_niche(session, "Baking")

    run_a = ResearchRun(
        creator_id=creator.id, status="completed", niche_id=niche_a.id,
    )
    run_b = ResearchRun(
        creator_id=creator.id, status="completed", niche_id=niche_b.id,
    )
    session.add_all([run_a, run_b])
    await session.flush()

    # Opportunity A: lower score but evidence from niche_a's run
    cluster_a = ProblemCluster(
        creator_id=creator.id, label="Grinder confusion", frequency=3, evidence_strength=0.8
    )
    session.add(cluster_a)
    await session.flush()
    ev_a = await _make_evidence(session, run_a.id, "espresso grinder issue")
    obs_a = ProblemObservation(
        evidence_id=ev_a.id, text=ev_a.raw_text, is_inferred=False,
        extraction_prompt_version="v1", model_version="fixture",
    )
    session.add(obs_a)
    await session.flush()
    session.add(ProblemClusterMember(
        cluster_id=cluster_a.id, observation_id=obs_a.id, similarity_score=0.9,
    ))
    opp_a = OpportunityScore(
        creator_id=creator.id, problem_cluster_id=cluster_a.id,
        component_scores={"frequency": 0.6}, aggregate_score=0.60,
        computed_hash="hash_a", confidence_band=ConfidenceBand.MEDIUM,
        rule_version="v1", model_version="fixture", research_run_id=run_a.id,
    )
    session.add(opp_a)

    # Opportunity B: higher score but evidence from niche_b's run
    cluster_b = ProblemCluster(
        creator_id=creator.id, label="Sourdough starter", frequency=5, evidence_strength=0.9
    )
    session.add(cluster_b)
    await session.flush()
    ev_b = await _make_evidence(session, run_b.id, "sourdough baking question")
    obs_b = ProblemObservation(
        evidence_id=ev_b.id, text=ev_b.raw_text, is_inferred=False,
        extraction_prompt_version="v1", model_version="fixture",
    )
    session.add(obs_b)
    await session.flush()
    session.add(ProblemClusterMember(
        cluster_id=cluster_b.id, observation_id=obs_b.id, similarity_score=0.9,
    ))
    opp_b = OpportunityScore(
        creator_id=creator.id, problem_cluster_id=cluster_b.id,
        component_scores={"frequency": 0.9}, aggregate_score=0.90,
        computed_hash="hash_b", confidence_band=ConfidenceBand.HIGH,
        rule_version="v1", model_version="fixture", research_run_id=run_b.id,
    )
    session.add(opp_b)

    session.add(CreatorScore(
        creator_id=creator.id, component_scores={"frequency": 0.75},
        aggregate_score=0.75, computed_hash="hash_cs",
        confidence_band=ConfidenceBand.HIGH, rule_version="v1", model_version="fixture",
    ))
    await session.commit()

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    dossier = await gen.generate_and_persist(creator.id, niche_a.id)
    await session.commit()

    # Dossier for niche_a should reference niche_a's opportunity (0.60),
    # not the global top (0.90 from niche_b).
    assert dossier.opportunity_score_id == opp_a.id
    assert dossier.niche_id == niche_a.id


@pytest.mark.asyncio
async def test_no_opportunities_raises(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    with pytest.raises(ValueError, match="no active opportunity scores"):
        await gen.generate_and_persist(creator.id, niche.id)


@pytest.mark.asyncio
async def test_niche_not_found_raises(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    run = await _make_run(session, creator.id)
    await _make_scored_opportunity(session, creator, run)

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    with pytest.raises(ValueError, match="Niche not found"):
        await gen.generate_and_persist(creator.id, "does-not-exist")


# ---------- R6: niche-scoped demand validation ----------


async def _niche_evidence(
    session: AsyncSession, run_id: str | None, platform: str, ev_type: EvidenceType, text: str
) -> Evidence:
    evidence = Evidence(
        source_type="post",
        source_id=f"{platform}_{text[:16]}",
        source_platform=platform,
        raw_text=text,
        access_method=AccessMethod.OPEN,
        compliance_status=ComplianceStatus.COMPLIANT,
        research_run_id=run_id,
        origin=EvidenceOrigin.OBSERVATION,
        evidence_type=ev_type,
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def _promoted_candidate(
    session: AsyncSession, campaign: Campaign, run: ResearchRun, niche: Niche, *evidence: Evidence
) -> NicheCandidate:
    candidate = NicheCandidate(
        campaign_id=campaign.id,
        research_run_id=run.id,
        label=niche.canonical_name,
        naming_method="llm",
        evidence_count=len(evidence),
        source_count=len({e.source_platform for e in evidence}),
        author_count=0,
        status=NicheCandidateStatus.PROMOTED,
        niche_id=niche.id,
    )
    session.add(candidate)
    await session.flush()
    for ev in evidence:
        session.add(NicheCandidateEvidence(candidate_id=candidate.id, evidence_id=ev.id))
    await session.flush()
    return candidate


@pytest.mark.asyncio
async def test_demand_validation_counts_niche_drill_and_research_more_evidence(
    clean_db: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """Niche-level demand evidence is never on a creator run: the depth-0
    drill links it to the promoted NicheCandidate, research_more tags the
    run with niche_id. The dossier must see both, and only for ITS niche."""
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    other = await _make_niche(session, "Sourdough")
    campaign = Campaign(name="R6")
    session.add(campaign)
    await session.flush()

    # Creator-level research run (no niche_id) backing the scored opportunity.
    creator_run = await _make_run(session, creator.id)
    await _make_scored_opportunity(session, creator, creator_run)

    # Depth-0 drill run: creator_id NULL, niche_id NULL; evidence reaches the
    # niche only through NicheCandidateEvidence.
    drill_run = ResearchRun(creator_id=None, status="completed", campaign_id=campaign.id)
    session.add(drill_run)
    await session.flush()
    trend = await _niche_evidence(
        session, drill_run.id, "googletrends", EvidenceType.TREND, "espresso rising"
    )
    txn = await _niche_evidence(
        session, drill_run.id, "marketplace", EvidenceType.TRANSACTION, "espresso guide $19"
    )
    await _promoted_candidate(session, campaign, drill_run, niche, trend, txn)

    # research_more-style run tagged with the niche directly.
    rm_run = ResearchRun(
        creator_id=None, status="completed", campaign_id=campaign.id, niche_id=niche.id
    )
    session.add(rm_run)
    await session.flush()
    await _niche_evidence(
        session, rm_run.id, "patreon_substack", EvidenceType.MONETISATION, "espresso newsletter"
    )

    # Another niche's drill evidence must NOT leak into this dossier.
    other_ev = await _niche_evidence(
        session, drill_run.id, "crowdfunding", EvidenceType.TRANSACTION, "sourdough kit"
    )
    await _promoted_candidate(session, campaign, drill_run, other, other_ev)
    await session.commit()

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    with caplog.at_level("WARNING", logger="corp.workers.dossier.generator"):
        dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    dv = dossier.content["demand_validation"]
    assert dv["signals"]["trend"] == 1
    assert dv["signals"]["transaction"] == 1  # marketplace only; crowdfunding is Sourdough's
    assert dv["signals"]["monetisation"] == 1
    assert dv["evidence_by_platform"] == {
        "youtube": 1, "googletrends": 1, "marketplace": 1, "patreon_substack": 1,
    }
    assert dv["platform_highlights"]["crowdfunding_signals"] == 0
    assert dv["platform_highlights"]["patreon_substack_indicators"] == 1
    assert dv["platform_highlights"]["marketplace_competition"] == 1
    assert dv["platform_highlights"]["google_trends"] == 1
    assert dv["evidence_by_type"]["problem"] == 1

    audience = dossier.content["audience_analysis"]
    assert audience["recurring_themes"][0]["label"] == "Grinder confusion"
    assert audience["engagement_quality"]["total_audience_observations"] == 1


@pytest.mark.asyncio
async def test_niche_filter_uses_candidate_evidence_not_only_run_niche_id(
    clean_db: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """An opportunity whose observation evidence was collected by the drill
    (linked via the promoted candidate) counts as niche-relevant, so the
    'using global top' fallback is not taken."""
    session = clean_db
    creator = await _make_creator(session)
    niche = await _make_niche(session, "Home Espresso")
    campaign = Campaign(name="R6b")
    session.add(campaign)
    await session.flush()

    other = await _make_niche(session, "Sourdough")

    drill_run = ResearchRun(creator_id=None, status="completed", campaign_id=campaign.id)
    session.add(drill_run)
    await session.flush()
    _, opp, evidence = await _make_scored_opportunity(
        session, creator, drill_run, aggregate_score=0.55, label="Grinder confusion"
    )
    await _promoted_candidate(session, campaign, drill_run, niche, evidence)

    # A HIGHER-scored opportunity whose evidence belongs to the sibling niche:
    # the global-top fallback would pick this one.
    _, other_opp, other_ev = await _make_scored_opportunity(
        session, creator, drill_run, aggregate_score=0.95, label="Sourdough starter",
        with_creator_score=False,
    )
    await _promoted_candidate(session, campaign, drill_run, other, other_ev)
    await session.commit()

    gen = DossierGenerator(session, rules_path=RULES_PATH)
    with caplog.at_level("WARNING", logger="corp.workers.dossier.generator"):
        dossier = await gen.generate_and_persist(creator.id, niche.id)
    await session.commit()

    assert dossier.opportunity_score_id == opp.id
    assert dossier.opportunity_score_id != other_opp.id
    assert "using global top" not in caplog.text
