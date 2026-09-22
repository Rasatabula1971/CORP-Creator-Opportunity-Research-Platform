"""Integration tests for IntentPipeline against real Postgres."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator
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
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.intent import INTENT_PROMPT_VERSION
from corp.workers.intelligence.intent_pipeline import IntentPipeline
from corp.workers.providers.registry import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, level: str = "strong") -> None:
        self._level = level

    @property
    def model_name(self) -> str:
        return "fake-intent-model"

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
        return {
            "signal_level": self._level,
            "rationale": f"Classified as {self._level} based on evidence",
            "confidence": 0.85,
            "key_indicators": ["buy", "pricing"],
        }


async def _seed_cluster(session: AsyncSession) -> tuple[Creator, ProblemCluster]:
    """Create creator → evidence → observations → cluster with members."""
    creator = Creator(name="IntentTest", niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()

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
        label="Battery Problems",
        description="Users complain about battery drain",
        frequency=5,
        recency_score=0.8,
        evidence_strength=0.7,
        model_version="test",
    )
    session.add(cluster)
    await session.flush()

    for i in range(3):
        evidence = Evidence(
            source_type="comment",
            source_id=f"intent_cmt_{i}",
            source_platform="youtube",
            raw_text=f"Where can I buy a battery replacement #{i}?",
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
            research_run_id=run.id,
        )
        session.add(evidence)
        await session.flush()

        obs = ProblemObservation(
            evidence_id=evidence.id,
            text=f"Where can I buy a battery replacement #{i}?",
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
            similarity_score=0.95,
        )
        session.add(member)

    await session.flush()
    return creator, cluster


@pytest.mark.asyncio
async def test_intent_pipeline_creates_run(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed_cluster(session)
    pipeline = IntentPipeline(FakeProvider(), session)

    run = await pipeline.run(creator.id)

    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.prompt_versions["intent"] == INTENT_PROMPT_VERSION
    assert run.model_versions["primary"] == "fake-intent-model"


@pytest.mark.asyncio
async def test_intent_pipeline_creates_commercial_signal(clean_db: AsyncSession):
    session = clean_db
    creator, cluster = await _seed_cluster(session)
    pipeline = IntentPipeline(FakeProvider(), session)

    await pipeline.run(creator.id)

    result = await session.execute(
        select(CommercialSignal).where(
            CommercialSignal.problem_cluster_id == cluster.id
        )
    )
    signal = result.scalar_one()

    assert signal.signal_level == SignalLevel.STRONG
    assert signal.confidence == 0.85
    assert signal.classification_model == "fake-intent-model"
    assert signal.prompt_version == INTENT_PROMPT_VERSION
    assert signal.rationale


@pytest.mark.asyncio
async def test_intent_pipeline_creates_evidence(clean_db: AsyncSession):
    session = clean_db
    creator, cluster = await _seed_cluster(session)
    pipeline = IntentPipeline(FakeProvider(), session)

    await pipeline.run(creator.id)

    result = await session.execute(
        select(CommercialSignal).where(
            CommercialSignal.problem_cluster_id == cluster.id
        )
    )
    signal = result.scalar_one()

    ev_result = await session.execute(
        select(Evidence).where(Evidence.id == signal.evidence_id)
    )
    evidence = ev_result.scalar_one()
    assert evidence.source_type == "intent_classification"
    assert evidence.source_id == cluster.id
    assert evidence.origin is EvidenceOrigin.INFERENCE
    assert evidence.evidence_type is EvidenceType.PROBLEM


@pytest.mark.asyncio
async def test_intent_pipeline_validation_level(clean_db: AsyncSession):
    session = clean_db
    creator, cluster = await _seed_cluster(session)
    pipeline = IntentPipeline(FakeProvider(level="validation"), session)

    await pipeline.run(creator.id)

    result = await session.execute(
        select(CommercialSignal).where(
            CommercialSignal.problem_cluster_id == cluster.id
        )
    )
    signal = result.scalar_one()
    assert signal.signal_level == SignalLevel.VALIDATION


@pytest.mark.asyncio
async def test_intent_pipeline_no_clusters(clean_db: AsyncSession):
    session = clean_db
    creator = Creator(name="NoClusters", niche="test", discovery_source="manual")
    session.add(creator)
    await session.flush()

    pipeline = IntentPipeline(FakeProvider(), session)
    run = await pipeline.run(creator.id)

    assert run.status == "completed"
    result = await session.execute(select(CommercialSignal))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_intent_pipeline_failure_marks_run_failed(clean_db: AsyncSession):
    session = clean_db
    creator, _ = await _seed_cluster(session)

    class BrokenProvider(LLMProvider):
        @property
        def model_name(self) -> str:
            return "broken"

        async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
            raise RuntimeError("LLM crashed")

    pipeline = IntentPipeline(BrokenProvider(), session)

    # Every unit failed: the run comes back "failed" rather than raising, so the
    # caller's commit keeps the row (docs/DECISIONS/0009).
    returned = await pipeline.run(creator.id)
    assert returned.status == "failed"

    result = await session.execute(
        select(ResearchRun).where(
            ResearchRun.config_snapshot["pipeline"].astext == "intent"
        )
    )
    run = result.scalar_one()
    assert run is returned
    assert run.status == "failed"
    assert "LLM crashed" in run.error_message
    assert run.completed_at is not None
