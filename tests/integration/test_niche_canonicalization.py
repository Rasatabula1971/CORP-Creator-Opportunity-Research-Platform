"""Integration tests for NicheCanonicalizer against real Postgres."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.niche import Niche, NicheAlias, NicheLifecycleStatus
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateEvidence,
    NicheCandidateStatus,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.workers.intelligence.embeddings import EMBEDDING_DIM
from corp.workers.intelligence.niche_canonicalization import CanonConfig, NicheCanonicalizer

# ── fakes ─────────────────────────────────────────────────────────────


class FakeEmbedder:
    """Assigns embeddings based on keywords so 'espresso' labels cluster together."""

    model_name = "fake-embedder"

    def encode(self, texts: list[str]) -> np.ndarray:
        rng = np.random.RandomState(42)
        out = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            vec = rng.randn(EMBEDDING_DIM).astype(np.float32) * 0.01
            low = text.lower()
            if "espresso" in low:
                vec[0] = 10.0
            elif "aquarium" in low or "reef" in low:
                vec[1] = 10.0
            elif "sim racing" in low or "racing" in low:
                vec[2] = 10.0
            else:
                vec[3] = 10.0
            out[i] = vec
        return out


# ── helpers ───────────────────────────────────────────────────────────


async def _seed_campaign_with_candidates(
    session: AsyncSession,
    labels: list[str],
    *,
    campaign_name: str = "Test Campaign",
) -> tuple[Campaign, list[NicheCandidate]]:
    campaign = Campaign(name=campaign_name)
    session.add(campaign)
    await session.flush()

    run = ResearchRun(
        creator_id=None,
        campaign_id=campaign.id,
        run_type=RunType.NICHE_DISCOVERY.value,
        scope=RunScope.NICHE.value,
        status="completed",
        config_snapshot={"pipeline": "niche_candidates"},
        prompt_versions={},
        model_versions={},
    )
    session.add(run)
    await session.flush()

    base = datetime(2026, 9, 1, tzinfo=UTC)
    candidates = []
    for i, label in enumerate(labels):
        ev = Evidence(
            source_type="video",
            source_id=f"vid-{i}",
            source_platform="youtube",
            raw_text=f"Evidence about {label}",
            author_handle=f"chan{i}",
            access_method=AccessMethod.VENDOR_SCRAPE,
            compliance_status=ComplianceStatus.VERIFY,
            research_run_id=run.id,
            collected_at=base + timedelta(days=i),
        )
        session.add(ev)
        await session.flush()

        cand = NicheCandidate(
            campaign_id=campaign.id,
            research_run_id=run.id,
            label=label,
            description=f"A niche about {label}",
            naming_method="llm",
            evidence_count=3 + i,
            source_count=1,
            author_count=2 + i,
            earliest_collected_at=base,
            latest_collected_at=base + timedelta(days=i),
            embedding_model="fake-embedder",
            naming_prompt_version="niche_name_v1",
            naming_model_version="fake-namer",
        )
        session.add(cand)
        await session.flush()

        session.add(
            NicheCandidateEvidence(
                candidate_id=cand.id,
                evidence_id=ev.id,
                similarity=0.95,
            )
        )
        await session.flush()
        candidates.append(cand)

    return campaign, candidates


# ── tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_promotes_all_unique_candidates(clean_db: AsyncSession):
    """Three distinct candidates → three new Niche rows, all PROMOTED."""
    session = clean_db
    campaign, cands = await _seed_campaign_with_candidates(
        session, ["Home Espresso", "Reef Aquarium Nitrates", "Sim Racing Hardware"]
    )
    canon = NicheCanonicalizer(FakeEmbedder(), session)
    run = await canon.canonicalize(campaign.id)

    assert run.status == "completed"
    extra = run.stats["extra"]
    assert extra["candidates"] == 3
    assert extra["promoted"] == 3
    assert extra["merged"] == 0
    assert extra["campaign_niches_created"] == 3

    niches = (await session.execute(select(Niche))).scalars().all()
    assert len(niches) == 3
    assert {n.canonical_name for n in niches} == {
        "Home Espresso",
        "Reef Aquarium Nitrates",
        "Sim Racing Hardware",
    }
    assert all(n.lifecycle_status == NicheLifecycleStatus.CANDIDATE for n in niches)

    for cand in cands:
        await session.refresh(cand)
        assert cand.status == NicheCandidateStatus.PROMOTED
        assert cand.niche_id is not None

    cn_rows = (await session.execute(select(CampaignNiche))).scalars().all()
    assert len(cn_rows) == 3
    assert all(cn.campaign_id == campaign.id for cn in cn_rows)


@pytest.mark.asyncio
async def test_merges_exact_name_match_same_case(clean_db: AsyncSession):
    """A candidate whose label matches an existing canonical_name (case-insensitive)
    is merged, and no redundant alias is created."""
    session = clean_db
    existing = Niche(canonical_name="Home Espresso")
    session.add(existing)
    await session.flush()

    campaign, cands = await _seed_campaign_with_candidates(
        session, ["home espresso"]
    )
    canon = NicheCanonicalizer(FakeEmbedder(), session)
    run = await canon.canonicalize(campaign.id)

    assert run.stats["extra"]["promoted"] == 0
    assert run.stats["extra"]["merged"] == 1

    await session.refresh(cands[0])
    assert cands[0].status == NicheCandidateStatus.MERGED
    assert cands[0].niche_id == existing.id

    aliases = (await session.execute(select(NicheAlias))).scalars().all()
    assert len(aliases) == 0

    niches = (await session.execute(select(Niche))).scalars().all()
    assert len(niches) == 1


@pytest.mark.asyncio
async def test_merges_different_label_creates_alias(clean_db: AsyncSession):
    """A candidate merged by embedding similarity gets its distinct label added as an alias."""
    session = clean_db
    existing = Niche(canonical_name="Home Espresso")
    session.add(existing)
    await session.flush()

    campaign, cands = await _seed_campaign_with_candidates(
        session, ["Espresso Machine Repair"]
    )
    canon = NicheCanonicalizer(FakeEmbedder(), session, CanonConfig(similarity_threshold=0.5))
    run = await canon.canonicalize(campaign.id)

    assert run.stats["extra"]["merged"] == 1

    await session.refresh(cands[0])
    assert cands[0].niche_id == existing.id

    aliases = (await session.execute(select(NicheAlias))).scalars().all()
    assert len(aliases) == 1
    assert aliases[0].alias == "Espresso Machine Repair"
    assert aliases[0].niche_id == existing.id


@pytest.mark.asyncio
async def test_merges_via_alias_match(clean_db: AsyncSession):
    """A candidate that matches an existing alias is merged into that alias's niche."""
    session = clean_db
    niche = Niche(canonical_name="Home Espresso")
    session.add(niche)
    await session.flush()
    session.add(NicheAlias(niche_id=niche.id, alias="espresso hobby"))
    await session.flush()

    campaign, cands = await _seed_campaign_with_candidates(
        session, ["Espresso Hobby"]
    )
    canon = NicheCanonicalizer(FakeEmbedder(), session)
    run = await canon.canonicalize(campaign.id)

    assert run.stats["extra"]["merged"] == 1
    await session.refresh(cands[0])
    assert cands[0].niche_id == niche.id


@pytest.mark.asyncio
async def test_merges_by_embedding_similarity(clean_db: AsyncSession):
    """Two candidates with very similar embeddings → the higher-evidence one is
    promoted (candidates are processed evidence_count DESC), the other merged."""
    session = clean_db
    campaign, cands = await _seed_campaign_with_candidates(
        session, ["Home Espresso Machines", "Espresso Troubleshooting"]
    )
    # cands[0] has evidence_count=3, cands[1] has evidence_count=4 (3+i)
    # So cands[1] is processed first (higher evidence) and promoted.
    canon = NicheCanonicalizer(FakeEmbedder(), session, CanonConfig(similarity_threshold=0.5))
    run = await canon.canonicalize(campaign.id)

    assert run.stats["extra"]["promoted"] == 1
    assert run.stats["extra"]["merged"] == 1

    niches = (await session.execute(select(Niche))).scalars().all()
    assert len(niches) == 1
    assert niches[0].canonical_name == "Espresso Troubleshooting"

    await session.refresh(cands[0])
    assert cands[0].status == NicheCandidateStatus.MERGED
    assert cands[0].niche_id == niches[0].id


@pytest.mark.asyncio
async def test_no_duplicate_alias_when_label_is_canonical(clean_db: AsyncSession):
    """When a candidate label matches an existing canonical_name exactly,
    no alias is created (it would be redundant)."""
    session = clean_db
    existing = Niche(canonical_name="Reef Aquariums")
    session.add(existing)
    await session.flush()

    campaign, _ = await _seed_campaign_with_candidates(session, ["Reef Aquariums"])
    canon = NicheCanonicalizer(FakeEmbedder(), session)
    await canon.canonicalize(campaign.id)

    aliases = (await session.execute(select(NicheAlias))).scalars().all()
    assert len(aliases) == 0


@pytest.mark.asyncio
async def test_campaign_niche_not_duplicated(clean_db: AsyncSession):
    """Running canonicalize twice does not create duplicate CampaignNiche rows."""
    session = clean_db
    campaign, _ = await _seed_campaign_with_candidates(
        session, ["Home Espresso"]
    )
    canon = NicheCanonicalizer(FakeEmbedder(), session)

    run1 = await canon.canonicalize(campaign.id)
    assert run1.stats["extra"]["campaign_niches_created"] == 1

    # Re-seed a new candidate for the same campaign with same label
    run_row = ResearchRun(
        creator_id=None,
        campaign_id=campaign.id,
        run_type=RunType.NICHE_DISCOVERY.value,
        scope=RunScope.NICHE.value,
        status="completed",
        config_snapshot={"pipeline": "niche_candidates"},
        prompt_versions={},
        model_versions={},
    )
    session.add(run_row)
    await session.flush()
    cand2 = NicheCandidate(
        campaign_id=campaign.id,
        research_run_id=run_row.id,
        label="Home Espresso",
        naming_method="llm",
        evidence_count=5,
        source_count=1,
        author_count=3,
        embedding_model="fake-embedder",
    )
    session.add(cand2)
    await session.flush()

    ev2 = Evidence(
        source_type="video",
        source_id="vid-dup",
        source_platform="youtube",
        raw_text="More espresso stuff",
        author_handle="chan99",
        access_method=AccessMethod.VENDOR_SCRAPE,
        compliance_status=ComplianceStatus.VERIFY,
        research_run_id=run_row.id,
        collected_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    session.add(ev2)
    await session.flush()
    session.add(NicheCandidateEvidence(candidate_id=cand2.id, evidence_id=ev2.id, similarity=0.9))
    await session.flush()

    run2 = await canon.canonicalize(campaign.id)
    assert run2.stats["extra"]["campaign_niches_created"] == 0

    cn_count = (
        await session.execute(select(func.count()).select_from(CampaignNiche))
    ).scalar()
    assert cn_count == 1


@pytest.mark.asyncio
async def test_empty_campaign_completes(clean_db: AsyncSession):
    session = clean_db
    campaign = Campaign(name="Empty")
    session.add(campaign)
    await session.flush()

    canon = NicheCanonicalizer(FakeEmbedder(), session)
    run = await canon.canonicalize(campaign.id)
    assert run.status == "completed"
    assert run.stats["extra"] == {
        "candidates": 0,
        "promoted": 0,
        "merged": 0,
        "campaign_niches_created": 0,
    }


@pytest.mark.asyncio
async def test_only_staged_candidates_are_processed(clean_db: AsyncSession):
    """PROMOTED/MERGED/REJECTED candidates are skipped."""
    session = clean_db
    campaign, cands = await _seed_campaign_with_candidates(
        session, ["Home Espresso", "Reef Aquariums"]
    )
    cands[0].status = NicheCandidateStatus.REJECTED
    await session.flush()

    canon = NicheCanonicalizer(FakeEmbedder(), session)
    run = await canon.canonicalize(campaign.id)
    assert run.stats["extra"]["candidates"] == 1
    assert run.stats["extra"]["promoted"] == 1


@pytest.mark.asyncio
async def test_superseded_candidates_are_skipped(clean_db: AsyncSession):
    session = clean_db
    campaign, cands = await _seed_campaign_with_candidates(
        session, ["Home Espresso", "Reef Aquariums"]
    )
    cands[0].superseded_at = datetime.now(UTC)
    await session.flush()

    canon = NicheCanonicalizer(FakeEmbedder(), session)
    run = await canon.canonicalize(campaign.id)
    assert run.stats["extra"]["candidates"] == 1
