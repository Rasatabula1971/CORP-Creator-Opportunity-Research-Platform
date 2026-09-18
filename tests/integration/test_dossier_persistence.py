"""Integration tests for DossierGenerator.generate_and_persist (CORP1
Stage 5, T6) against real Postgres."""


import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator
from corp.core.models.dossier import Dossier, DossierEvidence
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember, ProblemObservation
from corp.core.models.niche import Niche
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
