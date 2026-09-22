"""Integration tests for NicheCandidateGenerator against real Postgres."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateEvidence,
    NicheCandidateStatus,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.workers.intelligence.embeddings import EMBEDDING_DIM
from corp.workers.intelligence.niche_candidates import NicheCandidateGenerator
from corp.workers.providers.registry import LLMProvider

# ── fakes ─────────────────────────────────────────────────────────────


class FakeEmbedder:
    """Three clearly separated groups keyed on a word in the text."""

    model_name = "fake-embedder"

    def encode(self, texts: list[str]) -> np.ndarray:
        rng = np.random.RandomState(7)
        out = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            vec = rng.randn(EMBEDDING_DIM).astype(np.float32) * 0.01
            low = text.lower()
            axis = 0 if "espresso" in low else 1 if "aquarium" in low else 2
            vec[axis] = 10.0
            out[i] = vec
        return out


class NamingProvider(LLMProvider):
    """Names espresso clusters with grounded terms, aquarium ones with an ungrounded term."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "fake-namer"

    def models_used(self) -> set[str]:
        return {"fake-namer"}

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
        self.calls += 1
        if self._fail:
            raise RuntimeError("LLM down")
        if "espresso" in prompt.lower():
            return {
                "name": "Home Espresso",
                "description": "Home espresso troubleshooting.",
                "is_broad_domain": False,
                "confidence": 0.9,
                "evidence_terms": ["espresso machine", "grind"],
            }
        return {
            "name": "Marine Hobby",
            "description": "made up",
            "is_broad_domain": True,
            "confidence": 0.4,
            "evidence_terms": ["saltwater dosing pumps"],  # not in the texts
        }


ESPRESSO = [
    "Espresso machine leaking from the group head",
    "Espresso machine pressure too low, grind too coarse",
    "Dialing in grind for a new espresso machine",
    "Espresso machine descaling every month",
]
AQUARIUM = [
    "Reef aquarium nitrate keeps climbing",
    "Aquarium lighting schedule for corals",
    "Cycling a new aquarium before adding fish",
]
NOISE = ["Weekend vlog: road trip to the coast"]


async def _seed(
    session: AsyncSession, texts: list[str], *, platforms: list[str] | None = None
) -> Campaign:
    campaign = Campaign(name="Candidates Test")
    session.add(campaign)
    await session.flush()
    run = ResearchRun(
        creator_id=None,
        campaign_id=campaign.id,
        run_type=RunType.NICHE_DISCOVERY.value,
        scope=RunScope.NICHE.value,
        status="completed",
        config_snapshot={"pipeline": "niche_discovery"},
        prompt_versions={},
        model_versions={},
    )
    session.add(run)
    await session.flush()
    base = datetime(2026, 9, 1, tzinfo=UTC)
    for i, text in enumerate(texts):
        platform = platforms[i % len(platforms)] if platforms else "youtube"
        session.add(
            Evidence(
                source_type="video",
                source_id=f"vid-{i}",
                source_platform=platform,
                raw_text=text,
                author_handle=f"chan{i % 3}",
                access_method=AccessMethod.VENDOR_SCRAPE,
                compliance_status=ComplianceStatus.VERIFY,
                research_run_id=run.id,
                collected_at=base + timedelta(days=i),
                origin=EvidenceOrigin.OBSERVATION,
                evidence_type=EvidenceType.PROBLEM,
            )
        )
    await session.flush()
    return campaign


async def _candidates(session: AsyncSession, campaign_id: str, *, active_only: bool = True):
    stmt = select(NicheCandidate).where(NicheCandidate.campaign_id == campaign_id)
    if active_only:
        stmt = stmt.where(NicheCandidate.superseded_at.is_(None))
    result = await session.execute(stmt.order_by(NicheCandidate.evidence_count.desc()))
    return list(result.scalars().all())


# ── tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clusters_become_candidates_with_evidence_links(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed(session, ESPRESSO + AQUARIUM, platforms=["youtube", "reddit"])
    provider = NamingProvider()
    run = await NicheCandidateGenerator(FakeEmbedder(), provider, session).generate(campaign.id)

    assert run.status == "completed"
    assert run.run_type == RunType.NICHE_DISCOVERY.value
    assert run.campaign_id == campaign.id
    extra = run.stats["extra"]
    assert extra["evidence"] == 7
    assert extra["candidates"] == 2
    assert extra["noise"] == 0
    assert run.model_versions["used"] == ["fake-namer"]

    cands = await _candidates(session, campaign.id)
    assert [c.evidence_count for c in cands] == [4, 3]
    espresso, aquarium = cands

    # LLM name accepted: every cited term occurs in the member texts.
    assert espresso.label == "Home Espresso"
    assert espresso.naming_method == "llm"
    assert espresso.naming_terms == ["espresso machine", "grind"]
    assert espresso.is_broad_domain is False
    assert espresso.naming_prompt_version == "niche_name_v1"
    assert espresso.naming_model_version == "fake-namer"
    assert espresso.status == NicheCandidateStatus.STAGED
    assert espresso.research_run_id == run.id
    assert espresso.embedding_model == "fake-embedder"

    # LLM name rejected (ungrounded term): keyword label stands, audit trail kept.
    assert aquarium.naming_method == "keywords"
    assert "aquarium" in aquarium.label.lower()
    assert aquarium.extra["rejected_llm_name"] == "Marine Hobby"
    assert aquarium.extra["ungrounded_terms"] == ["saltwater dosing pumps"]
    assert aquarium.is_broad_domain is True  # the flag is still recorded

    # Diversity numbers are independent of the count (§18).
    assert espresso.source_count == 2
    assert espresso.author_count == 3
    assert espresso.earliest_collected_at < espresso.latest_collected_at

    # Every candidate references exactly its own evidence.
    members = (
        await session.execute(
            select(NicheCandidateEvidence, Evidence)
            .join(Evidence, Evidence.id == NicheCandidateEvidence.evidence_id)
            .where(NicheCandidateEvidence.candidate_id == espresso.id)
        )
    ).all()
    assert len(members) == 4
    assert all("espresso" in ev.raw_text.lower() for _, ev in members)
    assert all(0.0 <= m.similarity <= 1.0 for m, _ in members)


@pytest.mark.asyncio
async def test_noise_points_produce_nothing(clean_db: AsyncSession, monkeypatch):
    """HDBSCAN noise (label -1) is not a cluster, so it can never become a
    candidate; the clusterer is stubbed so the outcome does not depend on
    UMAP's behaviour on tiny inputs."""
    from corp.workers.intelligence import niche_candidates as module
    from corp.workers.intelligence.clustering import ClusterResult

    session = clean_db
    campaign = await _seed(session, ESPRESSO + NOISE)

    def fake_cluster(texts, embeddings, timestamps=None, config=None):
        idx = [i for i, t in enumerate(texts) if "espresso" in t.lower()]
        return [
            ClusterResult(
                label="Espresso Machine",
                description=texts[idx[0]],
                member_indices=idx,
                frequency=len(idx),
                recency_score=1.0,
                evidence_strength=1.0,
            )
        ]

    monkeypatch.setattr(module, "cluster_observations", fake_cluster)
    run = await NicheCandidateGenerator(FakeEmbedder(), None, session).generate(campaign.id)
    assert run.stats["extra"]["noise"] == 1
    (cand,) = await _candidates(session, campaign.id)
    assert cand.evidence_count == 4
    linked = (await session.execute(select(NicheCandidateEvidence.evidence_id))).scalars().all()
    noise_row = (
        await session.execute(select(Evidence).where(Evidence.raw_text == NOISE[0]))
    ).scalar_one()
    assert noise_row.id not in linked


@pytest.mark.asyncio
async def test_rerun_supersedes_staged_candidates(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed(session, ESPRESSO + AQUARIUM)
    gen = NicheCandidateGenerator(FakeEmbedder(), NamingProvider(), session)
    first = await gen.generate(campaign.id)
    second = await gen.generate(campaign.id)

    assert second.stats["extra"]["superseded"] == 2
    active = await _candidates(session, campaign.id)
    everything = await _candidates(session, campaign.id, active_only=False)
    assert len(active) == 2
    assert len(everything) == 4  # nothing deleted
    assert {c.research_run_id for c in active} == {second.id}
    assert all(c.superseded_at is not None for c in everything if c.research_run_id == first.id)


@pytest.mark.asyncio
async def test_no_evidence_completes_with_no_candidates(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Empty")
    session.add(campaign)
    await session.flush()
    run = await NicheCandidateGenerator(FakeEmbedder(), NamingProvider(), session).generate(
        campaign.id
    )
    assert run.status == "completed"
    assert run.stats["extra"] == {
        "evidence": 0,
        "superseded": 0,
        "clusters": 0,
        "candidates": 0,
        "noise": 0,
        "llm_naming_failures": 0,
        "llm_names_ungrounded": 0,
    }
    assert await _candidates(session, campaign.id) == []


@pytest.mark.asyncio
async def test_naming_failure_keeps_keyword_candidate(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed(session, ESPRESSO + AQUARIUM)
    provider = NamingProvider(fail=True)
    run = await NicheCandidateGenerator(FakeEmbedder(), provider, session).generate(campaign.id)
    assert run.status == "completed"  # a naming failure is not a candidate failure
    assert run.stats["extra"]["llm_naming_failures"] == 2
    cands = await _candidates(session, campaign.id)
    assert len(cands) == 2
    assert all(c.naming_method == "keywords" for c in cands)
    assert all("LLM down" in c.extra["naming_error"] for c in cands)


@pytest.mark.asyncio
async def test_no_provider_means_keyword_labels_only(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed(session, ESPRESSO + AQUARIUM)
    run = await NicheCandidateGenerator(FakeEmbedder(), None, session).generate(campaign.id)
    assert run.status == "completed"
    assert run.prompt_versions == {}
    cands = await _candidates(session, campaign.id)
    assert len(cands) == 2
    assert all(c.naming_method == "keywords" for c in cands)
    assert all(c.naming_prompt_version is None for c in cands)


@pytest.mark.asyncio
async def test_other_campaigns_evidence_is_not_used(clean_db: AsyncSession):
    session = clean_db
    mine = await _seed(session, ESPRESSO + AQUARIUM)
    await _seed(session, NOISE * 3)
    run = await NicheCandidateGenerator(FakeEmbedder(), None, session).generate(mine.id)
    assert run.stats["extra"]["evidence"] == 7
    assert [c.evidence_count for c in await _candidates(session, mine.id)] == [4, 3]


@pytest.mark.asyncio
async def test_candidate_without_evidence_is_impossible(clean_db: AsyncSession):
    session = clean_db
    campaign = await _seed(session, ESPRESSO)
    run = (await session.execute(select(ResearchRun))).scalar_one()
    session.add(
        NicheCandidate(
            campaign_id=campaign.id,
            research_run_id=run.id,
            label="Invented Niche",
            naming_method="llm",
            evidence_count=0,
            source_count=0,
            author_count=0,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_unknown_campaign_is_a_hard_error(clean_db: AsyncSession):
    with pytest.raises(ValueError, match="Campaign not found"):
        await NicheCandidateGenerator(FakeEmbedder(), None, clean_db).generate("nope")
