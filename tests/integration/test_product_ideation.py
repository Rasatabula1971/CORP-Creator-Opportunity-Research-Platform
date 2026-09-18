"""Integration tests for ProductIdeationGenerator (CORP1 Stage 5, T5)
against real Postgres."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember, ProblemObservation
from corp.core.models.product_idea import ProductIdea, ProductIdeaEvidence
from corp.workers.intelligence.product_ideation import ProductIdeationGenerator
from corp.workers.providers.registry import LLMProvider


def _config(**overrides: Any):
    import dataclasses

    from corp.workers.intelligence.product_ideation import IdeationConfig

    base = IdeationConfig(
        min_ideas=3,
        max_ideas=5,
        max_evidence_texts=40,
        max_text_chars=300,
        prompt_version="test_v1",
    )
    return dataclasses.replace(base, **overrides)


class ScriptedProvider(LLMProvider):
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "fake-ideation-provider"

    def models_used(self) -> set[str]:
        return {"fake-ideation-provider"}

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls += 1
        return self._response


def _idea(
    title: str,
    terms: list[str],
    idea_type: str = "template",
    complexity: str = "low",
) -> dict[str, Any]:
    return {
        "title": title,
        "description": f"{title} description",
        "type": idea_type,
        "complexity": complexity,
        "price_min": 19,
        "price_max": 39,
        "fit_rationale": f"Fits because {terms[0]}" if terms else "Fits",
        "evidence_terms": terms,
    }


async def _make_creator(session: AsyncSession, niche: str = "home espresso") -> Creator:
    creator = Creator(name="Coffee Creator", niche=niche, discovery_source="manual")
    session.add(creator)
    await session.flush()
    return creator


async def _make_cluster_with_evidence(
    session: AsyncSession,
    creator: Creator,
    texts: list[str],
    label: str = "Grinder confusion",
) -> ProblemCluster:
    cluster = ProblemCluster(
        creator_id=creator.id, label=label, frequency=len(texts), evidence_strength=0.8
    )
    session.add(cluster)
    await session.flush()

    for i, text in enumerate(texts):
        evidence = Evidence(
            source_type="comment",
            source_id=f"cmt_{label}_{i}",
            source_platform="youtube",
            raw_text=text,
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
        )
        session.add(evidence)
        await session.flush()

        obs = ProblemObservation(
            evidence_id=evidence.id,
            text=text,
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
    return cluster


# ---------- Generation ----------


@pytest.mark.asyncio
async def test_generates_ideas_for_cluster(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    await _make_cluster_with_evidence(
        session,
        creator,
        [
            "I wish there was a burr grinder comparison chart",
            "So confused about grind size for espresso",
            "Need a checklist for dialing in my grinder",
        ],
    )

    provider = ScriptedProvider(
        {
            "ideas": [
                _idea("Grinder Comparison Chart", ["grinder comparison"]),
                _idea("Grind Size Cheat Sheet", ["grind size"], idea_type="checklist"),
                _idea("Dial-In Checklist", ["checklist"], idea_type="checklist"),
            ]
        }
    )
    gen = ProductIdeationGenerator(provider, session, "unused", config=_config())
    run = await gen.generate(creator.id)

    assert run.status == "completed"
    result = await session.execute(select(ProductIdea).where(ProductIdea.creator_id == creator.id))
    ideas = result.scalars().all()
    assert len(ideas) == 3
    assert {i.title for i in ideas} == {
        "Grinder Comparison Chart",
        "Grind Size Cheat Sheet",
        "Dial-In Checklist",
    }
    for idea in ideas:
        assert idea.evidence_count >= 1
        assert idea.price_min == 19
        assert idea.price_max == 39
        assert idea.generation_model_version == "fake-ideation-provider"
        assert idea.generation_prompt_version == "test_v1"


# ---------- Provenance ----------


@pytest.mark.asyncio
async def test_provenance_links_to_real_evidence_rows(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    await _make_cluster_with_evidence(
        session, creator, ["I wish there was a burr grinder comparison chart"]
    )

    provider = ScriptedProvider(
        {"ideas": [_idea("Grinder Comparison Chart", ["grinder comparison"])]}
    )
    gen = ProductIdeationGenerator(provider, session, "unused", config=_config())
    await gen.generate(creator.id)

    idea = (
        await session.execute(select(ProductIdea).where(ProductIdea.creator_id == creator.id))
    ).scalar_one()
    links = (
        await session.execute(
            select(ProductIdeaEvidence).where(ProductIdeaEvidence.product_idea_id == idea.id)
        )
    ).scalars().all()
    assert len(links) == idea.evidence_count
    assert len(links) >= 1

    evidence_row = await session.get(Evidence, links[0].evidence_id)
    assert evidence_row is not None
    assert "grinder comparison" in evidence_row.raw_text.lower()


# ---------- Grounding ----------


@pytest.mark.asyncio
async def test_ungrounded_idea_dropped(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    await _make_cluster_with_evidence(session, creator, ["Need help choosing a grinder"])

    provider = ScriptedProvider(
        {"ideas": [_idea("Invented Product", ["term that never appears anywhere"])]}
    )
    gen = ProductIdeationGenerator(provider, session, "unused", config=_config())
    await gen.generate(creator.id)

    result = await session.execute(select(ProductIdea).where(ProductIdea.creator_id == creator.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_unknown_type_dropped(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    await _make_cluster_with_evidence(session, creator, ["Need help choosing a grinder"])

    provider = ScriptedProvider(
        {"ideas": [_idea("Bad Type Product", ["grinder"], idea_type="spaceship")]}
    )
    gen = ProductIdeationGenerator(provider, session, "unused", config=_config())
    await gen.generate(creator.id)

    result = await session.execute(select(ProductIdea).where(ProductIdea.creator_id == creator.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_missing_evidence_terms_dropped(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    await _make_cluster_with_evidence(session, creator, ["Need help choosing a grinder"])

    provider = ScriptedProvider({"ideas": [_idea("No Terms Product", [])]})
    gen = ProductIdeationGenerator(provider, session, "unused", config=_config())
    await gen.generate(creator.id)

    result = await session.execute(select(ProductIdea).where(ProductIdea.creator_id == creator.id))
    assert result.scalars().all() == []


# ---------- Rerun / supersession ----------


@pytest.mark.asyncio
async def test_rerun_supersedes_previous_ideas(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)
    await _make_cluster_with_evidence(session, creator, ["I wish there was a grinder chart"])

    provider1 = ScriptedProvider({"ideas": [_idea("First Idea", ["grinder chart"])]})
    gen1 = ProductIdeationGenerator(provider1, session, "unused", config=_config())
    await gen1.generate(creator.id)

    provider2 = ScriptedProvider({"ideas": [_idea("Second Idea", ["grinder chart"])]})
    gen2 = ProductIdeationGenerator(provider2, session, "unused", config=_config())
    await gen2.generate(creator.id)

    result = await session.execute(select(ProductIdea).where(ProductIdea.creator_id == creator.id))
    all_ideas = result.scalars().all()
    assert len(all_ideas) == 2  # never deleted

    active = [i for i in all_ideas if i.superseded_at is None]
    assert len(active) == 1
    assert active[0].title == "Second Idea"


# ---------- Edge cases ----------


@pytest.mark.asyncio
async def test_creator_not_found_raises(clean_db: AsyncSession):
    session = clean_db
    provider = ScriptedProvider({"ideas": []})
    gen = ProductIdeationGenerator(provider, session, "unused", config=_config())
    with pytest.raises(ValueError, match="Creator not found"):
        await gen.generate("does-not-exist")


@pytest.mark.asyncio
async def test_no_active_clusters_completes_with_no_ideas(clean_db: AsyncSession):
    session = clean_db
    creator = await _make_creator(session)

    provider = ScriptedProvider({"ideas": []})
    gen = ProductIdeationGenerator(provider, session, "unused", config=_config())
    run = await gen.generate(creator.id)

    assert run.status == "completed"
    assert provider.calls == 0
    result = await session.execute(select(ProductIdea).where(ProductIdea.creator_id == creator.id))
    assert result.scalars().all() == []
