"""End-to-end campaign pipeline test (CORP1 Stage 5, T4).

Proves the wiring T4 introduces: T3's recursive discovery engine feeds
directly into the existing, unchanged canonicalize -> verify ->
estimate-ecosystem -> qualify -> select -> onboard chain, with no manual
data patching between stages, all driven through jobs.run_campaign_pipeline
(the same dispatcher the API calls). Every external boundary (LLM,
adapters, embeddings) is faked; internal DB-only stages run for real.

The final "reaches a dossier" step calls CampaignResearchBatch directly
(jobs.py's "research-campaign" branch hardcodes a real ResearchOrchestrator
with no injection point) with the same FakeResearcher pattern
test_campaign_research_batch.py already validates against that exact
class -- proving the onboarded creators are shaped correctly for it,
without re-deriving ResearchOrchestrator's own internal collect ->
intelligence -> cluster -> scoring chain, which is unchanged by T4 and
already covered by its own test suite.
"""

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.api import jobs
from corp.config import settings
from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.core.models.intelligence import ProblemCluster
from corp.core.models.niche import Niche
from corp.core.models.niche_candidate import NicheCandidate, NicheCandidateStatus
from corp.core.models.scoring import ConfidenceBand, CreatorScore, OpportunityScore
from corp.workers.adapters.base import NormalizedContent
from corp.workers.dossier.generator import DossierGenerator
from corp.workers.intelligence.embeddings import EMBEDDING_DIM
from corp.workers.intelligence.runs import PipelineStats, finish_run, start_run
from corp.workers.providers.capabilities import TrendProvider
from corp.workers.providers.registry import LLMProvider
from corp.workers.scheduler.discovery_scan import run_discovery_pass

pytestmark = pytest.mark.asyncio

TOPIC = "coffee"
NICHE_LABEL = "Home Espresso"
EVIDENCE_TERM = "espresso"


# ---------- Fakes ----------


class _FakeDiscoveryAdapter:
    """One fake NICHE-family adapter, reused for every
    NICHE_FAN_OUT_PLATFORMS slot (mirrors test_niche_discovery.py's
    pattern). Returns enough evidence with enough distinct authors to
    clear NicheVerifier's default thresholds (min_evidence=5,
    min_authors=3)."""

    from corp.workers.adapters.base import AdapterFamily

    family = AdapterFamily.NICHE

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def platform(self) -> str:
        return "fakeniche"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        self.calls.append(identifier)
        return [
            NormalizedContent(
                source_platform="fakeniche",
                content_type="fixture",
                external_id=f"item_{i}",
                text=f"Looking for {EVIDENCE_TERM} gear recommendations, post {i}",
                author=f"author_{i % 4}",
                timestamp=datetime.now(tz=UTC),
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.COMPLIANT,
            )
            for i in range(6)
        ]


class _FakeTrendDiscoveryAdapter(_FakeDiscoveryAdapter, TrendProvider):
    async def fetch_trend(self, query: str) -> list[NormalizedContent]:
        return await self.collect(query)


class ScriptedProvider(LLMProvider):
    """Synthesizes exactly one specific-enough niche, grounded in the
    fake evidence's EVIDENCE_TERM."""

    @property
    def model_name(self) -> str:
        return "fake-e2e-provider"

    def models_used(self) -> set[str]:
        return {"fake-e2e-provider"}

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "niches": [
                {
                    "name": NICHE_LABEL,
                    "description": f"{NICHE_LABEL} description",
                    "specific_enough": True,
                    "evidence_terms": [EVIDENCE_TERM],
                }
            ]
        }


class FakeEmbedder:
    """No real clusters to separate (canonicalization runs against an
    empty Niche table, so every candidate is a fresh promotion, never a
    similarity merge) -- a constant deterministic vector is enough."""

    model_name = "fake-e2e-embedder"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.full((len(texts), EMBEDDING_DIM), 0.1, dtype=np.float32)


class FakeYouTubeSearchAdapter:
    """Returns one channel per niche query, with a follower count inside
    the default 10k-200k target band both estimate-ecosystem and onboard
    check against."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def collect(self, identifier: str) -> list[Any]:
        self.calls.append(identifier)

        class _Item:
            author = "Espresso Creator"
            metadata = {"channel_id": "UC" + "1" * 22, "follower_count": 50_000}

        return [_Item()]

    async def close(self) -> None:
        pass


class FakeResearcher:
    """Matches the CreatorResearcher Protocol CampaignResearchBatch
    accepts -- identical to test_campaign_research_batch.py's own fake,
    reused here to prove onboarded creators are shaped correctly for it
    without re-deriving ResearchOrchestrator's internals."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, creator_id: str, *, skip_collect: bool = False) -> Any:
        self.calls.append(creator_id)

        class _Report:
            final_status = "human_review"

        return _Report()


# ---------- The end-to-end test ----------


async def test_campaign_pipeline_discover_to_dossier(clean_db: AsyncSession, monkeypatch):
    session = clean_db

    fake_niche_adapter = _FakeTrendDiscoveryAdapter()
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter",
        lambda platform: fake_niche_adapter,
    )
    monkeypatch.setattr(
        "corp.workers.providers.factory.build_provider", lambda: ScriptedProvider()
    )
    monkeypatch.setattr(
        "corp.workers.intelligence.embeddings.SentenceTransformerEmbedder",
        lambda model_name: FakeEmbedder(),
    )
    fake_youtube = FakeYouTubeSearchAdapter()
    monkeypatch.setattr(
        "corp.workers.adapters.registry.build_search_adapter",
        lambda platform, cfg=None: fake_youtube,
    )
    # Real key present in this dev checkout's .env would otherwise make a
    # live YouTube Data API call trying to enrich a fake channel id.
    monkeypatch.setattr(settings, "youtube_api_key", "")

    campaign = Campaign(
        name="E2E Campaign",
        creator_min_followers=10_000,
        creator_max_followers=200_000,
    )
    session.add(campaign)
    await session.commit()

    # 1. discover (T4: now RecursiveNicheDiscovery, not the old collector)
    result = await jobs.run_campaign_pipeline("discover", campaign.id, query=TOPIC)
    assert result["status"] == "completed"

    candidates = (
        await session.execute(
            select(NicheCandidate).where(NicheCandidate.campaign_id == campaign.id)
        )
    ).scalars().all()
    assert len(candidates) == 1
    assert candidates[0].label == NICHE_LABEL
    assert candidates[0].status == NicheCandidateStatus.STAGED
    assert candidates[0].evidence_count >= 5

    # 2. canonicalize (existing, unchanged)
    result = await jobs.run_campaign_pipeline("canonicalize", campaign.id)
    assert result["status"] == "completed"

    niche = (
        await session.execute(select(Niche).where(Niche.canonical_name == NICHE_LABEL))
    ).scalar_one()

    # 3. verify (existing, unchanged) -- needs min_evidence=5, min_authors=3;
    # the fixture evidence provides 6 items across 4 distinct authors.
    result = await jobs.run_campaign_pipeline("verify", campaign.id)
    assert result["status"] == "completed"

    # 4. estimate-ecosystem (existing, unchanged)
    result = await jobs.run_campaign_pipeline("estimate-ecosystem", campaign.id)
    assert result["status"] == "completed"

    # 5. qualify (existing, unchanged, rules-driven, no external deps)
    result = await jobs.run_campaign_pipeline("qualify", campaign.id)
    assert result["status"] == "completed"

    # 6. select (existing, unchanged)
    result = await jobs.run_campaign_pipeline("select", campaign.id)
    assert result["status"] == "completed"

    cn = (
        await session.execute(
            select(CampaignNiche).where(
                CampaignNiche.campaign_id == campaign.id, CampaignNiche.niche_id == niche.id
            )
        )
    ).scalar_one()
    assert cn.status == CampaignNicheStatus.SELECTED

    # 7. onboard (existing, unchanged)
    result = await jobs.run_campaign_pipeline("onboard", campaign.id)
    assert result["status"] == "completed"

    creator = (
        await session.execute(select(Creator))
    ).scalars().first()
    assert creator is not None
    creator_niche = (
        await session.execute(
            select(CreatorNiche).where(
                CreatorNiche.creator_id == creator.id, CreatorNiche.niche_id == niche.id
            )
        )
    ).scalar_one_or_none()
    assert creator_niche is not None

    # 8. research-campaign's actual class (jobs.py hardcodes a real
    # ResearchOrchestrator with no injection point -- called directly
    # here with the same fake the orchestrator's own test suite uses)
    # accepts the onboarded creator with no manual data fixing.
    from corp.workers.campaign_research import CampaignResearchBatch

    researcher = FakeResearcher()
    batch = CampaignResearchBatch(researcher, session)
    run = await batch.run_campaign(campaign.id)
    await session.commit()
    assert run.status in ("completed", "partial")
    assert creator.id in researcher.calls

    # 9. Seed what a real research pass would have produced (scoring is
    # ResearchOrchestrator's job, unchanged and out of T4's scope) and
    # confirm the dossier generator -- the actual "reaches a dossier"
    # proof -- succeeds against this creator with no further manual setup.
    cluster = ProblemCluster(
        creator_id=creator.id, label="Gear questions", frequency=3, evidence_strength=0.7
    )
    session.add(cluster)
    await session.flush()
    session.add(
        CreatorScore(
            creator_id=creator.id,
            component_scores={"frequency": 0.7},
            aggregate_score=0.72,
            computed_hash="e2e-hash",
            confidence_band=ConfidenceBand.MEDIUM,
            rule_version="v1.0.0",
            model_version="fake",
        )
    )
    session.add(
        OpportunityScore(
            creator_id=creator.id,
            problem_cluster_id=cluster.id,
            component_scores={"frequency": 0.7},
            aggregate_score=0.72,
            computed_hash="e2e-hash-opp",
            confidence_band=ConfidenceBand.MEDIUM,
            rule_version="v1.0.0",
            model_version="fake",
        )
    )
    await session.commit()

    dossier_data = await DossierGenerator(session).generate_data(creator.id)
    assert dossier_data.creator.id == creator.id
    assert dossier_data.creator_score is not None
    assert len(dossier_data.opportunities) == 1
    assert dossier_data.opportunities[0].cluster.label == "Gear questions"


async def test_run_discovery_pass_auto_chains_the_whole_flow(
    clean_db: AsyncSession, monkeypatch,
):
    """The frozen flow's whole point: one call — the same one an
    unattended scheduler tick or a single POST /discovery/run makes —
    must carry a campaign all the way from a scan to onboarded, researched
    creators, with nobody clicking through canonicalize/verify/estimate-
    ecosystem/qualify/select/onboard/research-campaign by hand. Reuses the
    exact fakes test_campaign_pipeline_discover_to_dossier above already
    validates those stages against, driving them through
    run_discovery_pass (discovery_scan.py's _advance_campaign_to_gate)
    instead of jobs.run_campaign_pipeline called once per stage."""
    session = clean_db

    fake_niche_adapter = _FakeTrendDiscoveryAdapter()
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter",
        lambda platform: fake_niche_adapter,
    )
    monkeypatch.setattr(
        "corp.workers.intelligence.embeddings.SentenceTransformerEmbedder",
        lambda model_name: FakeEmbedder(),
    )
    fake_youtube = FakeYouTubeSearchAdapter()
    monkeypatch.setattr(
        "corp.workers.adapters.registry.build_search_adapter",
        lambda platform, cfg=None: fake_youtube,
    )
    # Real key present in this dev checkout's .env would otherwise make a
    # live YouTube Data API call trying to enrich a fake channel id.
    monkeypatch.setattr(settings, "youtube_api_key", "")

    # research-campaign's real path drives a full ResearchOrchestrator
    # (collect -> intelligence -> cluster -> intent -> score -> dossier);
    # like the manual-stage test above, that internal chain is out of
    # scope here and already covered by its own test suite. Fake only
    # this one call, so the assertion below is "did the auto-chain reach
    # and invoke research-campaign with the onboarded creator", not a
    # re-derivation of what that stage does internally.
    researched: list[str] = []

    async def fake_run_campaign(self: Any, campaign_id: str) -> Any:
        creators = (await session.execute(select(Creator))).scalars().all()
        researched.extend(c.id for c in creators)
        run = await start_run(
            session, pipeline="fake-research-campaign", creator_id=None,
            campaign_id=campaign_id,
        )
        return await finish_run(session, run, PipelineStats())

    monkeypatch.setattr(
        "corp.workers.campaign_research.CampaignResearchBatch.run_campaign",
        fake_run_campaign,
    )

    campaign = Campaign(
        name="Auto-chain Campaign",
        creator_min_followers=10_000,
        creator_max_followers=200_000,
    )
    session.add(campaign)
    await session.commit()

    stats = await run_discovery_pass(
        session, ScriptedProvider(), topics=[TOPIC], campaign_id=campaign.id,
    )
    await session.commit()

    assert stats.topics_drilled == 1
    for stage in (
        "canonicalize",
        "verify",
        "estimate_ecosystem",
        "qualify",
        "select",
        "onboard",
        "research_campaign",
    ):
        entry = stats.pipeline.get(stage)
        assert entry and "run_id" in entry, f"{stage} did not complete: {entry}"

    niche = (
        await session.execute(select(Niche).where(Niche.canonical_name == NICHE_LABEL))
    ).scalar_one()
    cn = (
        await session.execute(
            select(CampaignNiche).where(
                CampaignNiche.campaign_id == campaign.id, CampaignNiche.niche_id == niche.id
            )
        )
    ).scalar_one()
    assert cn.status == CampaignNicheStatus.SELECTED

    creator = (await session.execute(select(Creator))).scalars().first()
    assert creator is not None
    creator_niche = (
        await session.execute(
            select(CreatorNiche).where(
                CreatorNiche.creator_id == creator.id, CreatorNiche.niche_id == niche.id
            )
        )
    ).scalar_one_or_none()
    assert creator_niche is not None
    assert creator.id in researched, "research-campaign must have run against the onboarded creator"


async def test_run_discovery_pass_stops_the_chain_on_a_stage_failure(
    clean_db: AsyncSession, monkeypatch,
):
    """A stage that raises must stop the chain there — not run a later
    stage against incomplete input — and must not leak the exception's
    own text into stats.pipeline (that dict flows into the job's result,
    readable from GET /jobs/{job_id})."""
    session = clean_db

    fake_niche_adapter = _FakeTrendDiscoveryAdapter()
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter",
        lambda platform: fake_niche_adapter,
    )
    monkeypatch.setattr(
        "corp.workers.intelligence.embeddings.SentenceTransformerEmbedder",
        lambda model_name: FakeEmbedder(),
    )

    async def broken_verify(self: Any, campaign_id: str) -> Any:
        raise RuntimeError("connect to postgresql://corp:hunter2@db.internal failed")

    monkeypatch.setattr(
        "corp.workers.intelligence.niche_verification.NicheVerifier.verify", broken_verify,
    )

    campaign = Campaign(name="Broken-stage Campaign")
    session.add(campaign)
    await session.commit()

    stats = await run_discovery_pass(
        session, ScriptedProvider(), topics=[TOPIC], campaign_id=campaign.id,
    )
    await session.commit()

    assert "run_id" in stats.pipeline["canonicalize"]
    assert stats.pipeline["verify"]["status"] == "failed"
    assert "hunter2" not in str(stats.pipeline) and "db.internal" not in str(stats.pipeline)
    assert "estimate_ecosystem" not in stats.pipeline, "later stages must not run past a failure"
    assert "qualify" not in stats.pipeline
    assert stats.qualified is False
