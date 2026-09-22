"""Integration tests for NicheCanonicalizer against real Postgres."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche
from corp.core.models.evidence import (
    AccessMethod,
    ComplianceStatus,
    Evidence,
    EvidenceOrigin,
    EvidenceType,
)
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
            origin=EvidenceOrigin.OBSERVATION,
            evidence_type=EvidenceType.PROBLEM,
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
        origin=EvidenceOrigin.OBSERVATION,
        evidence_type=EvidenceType.PROBLEM,
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


# ── R4: tree lineage carried onto Niche ───────────────────────────────


async def _seed_tree(
    session: AsyncSession,
) -> tuple[Campaign, NicheCandidate, NicheCandidate]:
    """A depth-0 parent and a depth-1 child; the CHILD has more evidence so
    an evidence-count-first ordering would canonicalize it before its parent."""
    campaign, (parent, child) = await _seed_campaign_with_candidates(
        session, ["Home Espresso", "Burr Grinder Upgrades"], campaign_name="Tree"
    )
    child.parent_candidate_id = parent.id
    child.depth = 1
    child.evidence_count = parent.evidence_count + 10
    await session.flush()
    return campaign, parent, child


@pytest.mark.asyncio
async def test_promotion_carries_parent_and_depth_onto_niche(clean_db: AsyncSession):
    session = clean_db
    campaign, parent, child = await _seed_tree(session)

    run = await NicheCanonicalizer(FakeEmbedder(), session).canonicalize(campaign.id)
    assert run.stats["extra"]["promoted"] == 2

    await session.refresh(parent)
    await session.refresh(child)
    parent_niche = await session.get(Niche, parent.niche_id)
    child_niche = await session.get(Niche, child.niche_id)
    assert parent_niche is not None and child_niche is not None
    assert parent_niche.parent_niche_id is None
    assert parent_niche.depth == 0
    assert child_niche.parent_niche_id == parent_niche.id
    assert child_niche.depth == 1


@pytest.mark.asyncio
async def test_merge_fills_missing_lineage_but_never_reparents(clean_db: AsyncSession):
    session = clean_db
    campaign, parent, child = await _seed_tree(session)
    # Give the parent candidate its own resolvable parent so the "never
    # re-parent" branch is exercised for real, not short-circuited.
    _, (grand,) = await _seed_campaign_with_candidates(
        session, ["Reef Aquarium Lighting"], campaign_name="Grand"
    )
    grand.campaign_id = campaign.id
    parent.parent_candidate_id = grand.id
    parent.depth = 1
    child.depth = 2
    await session.flush()

    # Pre-existing niche the child will merge into (exact-name match), with
    # no lineage yet -- e.g. promoted before R4.
    orphan = Niche(canonical_name="Burr Grinder Upgrades")
    # Pre-existing niche that already HAS lineage and must be left alone.
    root = Niche(canonical_name="Coffee")
    session.add_all([orphan, root])
    await session.flush()
    rooted = Niche(canonical_name="Home Espresso", parent_niche_id=root.id, depth=1)
    session.add(rooted)
    await session.flush()

    run = await NicheCanonicalizer(FakeEmbedder(), session).canonicalize(campaign.id)
    assert run.stats["extra"]["merged"] == 2
    assert run.stats["extra"]["promoted"] == 1  # Reef Aquarium Lighting

    await session.refresh(orphan)
    await session.refresh(rooted)
    # child merged into orphan: lineage filled from the parent candidate's
    # niche, depth derived from that niche (rooted.depth + 1), not copied.
    assert orphan.parent_niche_id == rooted.id
    assert orphan.depth == 2
    # parent merged into rooted even though "Reef Aquarium Lighting" resolved as a
    # parent: existing lineage untouched.
    assert rooted.parent_niche_id == root.id
    assert rooted.depth == 1


@pytest.mark.asyncio
async def test_child_merging_into_its_parents_niche_is_not_self_parented(
    clean_db: AsyncSession,
):
    session = clean_db
    campaign, (parent, child) = await _seed_campaign_with_candidates(
        session, ["Home Espresso", "Home Espresso Setup"], campaign_name="Self"
    )
    child.parent_candidate_id = parent.id
    child.depth = 1
    await session.flush()

    # Both labels contain "espresso" -> FakeEmbedder puts them within the
    # similarity threshold, so the child merges into the parent's new niche.
    await NicheCanonicalizer(FakeEmbedder(), session).canonicalize(campaign.id)

    await session.refresh(child)
    await session.refresh(parent)
    assert child.status == NicheCandidateStatus.MERGED
    assert child.niche_id == parent.niche_id
    niche = await session.get(Niche, parent.niche_id)
    assert niche is not None
    assert niche.parent_niche_id is None
    assert niche.depth == 0


@pytest.mark.asyncio
async def test_merge_fill_refuses_to_create_a_deeper_cycle(clean_db: AsyncSession):
    """Run 1 promoted B(root) -> A(child). Run 2 drills the inverted tree
    A(depth 0) -> B(depth 1). B's niche has lineage-less... no: A's niche has
    lineage (untouched); B's niche is a root, and filling its parent with A's
    niche would make NA -> NB -> NA. The guard must refuse."""
    session = clean_db
    nb = Niche(canonical_name="Home Espresso")
    session.add(nb)
    await session.flush()
    na = Niche(canonical_name="Burr Grinder Upgrades", parent_niche_id=nb.id, depth=1)
    session.add(na)
    await session.flush()

    campaign, (a, b) = await _seed_campaign_with_candidates(
        session, ["Burr Grinder Upgrades", "Home Espresso"], campaign_name="Inverted"
    )
    b.parent_candidate_id = a.id
    b.depth = 1
    await session.flush()

    run = await NicheCanonicalizer(FakeEmbedder(), session).canonicalize(campaign.id)
    assert run.stats["extra"]["merged"] == 2

    await session.refresh(na)
    await session.refresh(nb)
    assert na.parent_niche_id == nb.id
    assert nb.parent_niche_id is None  # refused: NA is NB's descendant
    assert nb.depth == 0


@pytest.mark.asyncio
async def test_canonicalized_chain_yields_multi_node_dossier_path(clean_db: AsyncSession):
    """R4 acceptance: a drilled chain, once canonicalized, walks root-to-leaf
    through the same _niche_path the dossier generator persists."""
    from corp.workers.dossier.generator import DossierGenerator

    session = clean_db
    campaign, (root, mid, leaf) = await _seed_campaign_with_candidates(
        session, ["Kitchen Gadgets", "Home Espresso", "Sim Racing Wheels"],
        campaign_name="Chain",
    )
    mid.parent_candidate_id, mid.depth = root.id, 1
    leaf.parent_candidate_id, leaf.depth = mid.id, 2
    # Leaf has the most evidence: evidence-first ordering would break the chain.
    leaf.evidence_count = 99
    await session.flush()

    await NicheCanonicalizer(FakeEmbedder(), session).canonicalize(campaign.id)
    await session.refresh(leaf)

    path = await DossierGenerator(session, rules_path="rules/scoring.yaml")._niche_path(
        leaf.niche_id
    )
    assert [p["canonical_name"] for p in path] == [
        "Kitchen Gadgets", "Home Espresso", "Sim Racing Wheels"
    ]
    assert [p["depth"] for p in path] == [0, 1, 2]


# ── R5: research-registry clock starts at promotion ───────────────────


@pytest.mark.asyncio
async def test_promotion_starts_recheck_clock(clean_db: AsyncSession):
    session = clean_db
    campaign, (cand,) = await _seed_campaign_with_candidates(
        session, ["Home Espresso"], campaign_name="Clock"
    )
    before = datetime.now(UTC)
    await NicheCanonicalizer(
        FakeEmbedder(), session, CanonConfig(recheck_days=30)
    ).canonicalize(campaign.id)
    await session.refresh(cand)
    niche = await session.get(Niche, cand.niche_id)
    assert niche is not None
    assert niche.last_researched_at is not None and niche.last_researched_at >= before
    assert niche.next_recheck_at is not None
    assert abs((niche.next_recheck_at - niche.last_researched_at) - timedelta(days=30)) < timedelta(
        seconds=1
    )
