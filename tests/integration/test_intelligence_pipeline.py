"""Integration tests for IntelligencePipeline against real Postgres."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem, ContentType, InteractionType
from corp.core.models.creator import Creator
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.intelligence import ProblemObservation
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.extraction import EXTRACTION_PROMPT_VERSION
from corp.workers.intelligence.pipeline import IntelligencePipeline
from corp.workers.intelligence.topics import TOPIC_PROMPT_VERSION
from corp.workers.providers.registry import LLMProvider


class FakeProvider(LLMProvider):
    """Deterministic provider returning canned responses."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def model_name(self) -> str:
        return "fake-test-model"

    async def generate_json(self, prompt: str, system: str | None = None) -> dict:
        self._call_count += 1
        if "topic" in (system or "").lower() or "topics" in prompt.lower()[:100]:
            return {
                "topics": [
                    {"name": "Tech Reviews", "confidence": 0.9, "evidence_count": 1},
                ]
            }
        return {
            "observations": [
                {
                    "text": "Viewer has battery issues",
                    "category": "problem",
                    "is_inferred": False,
                    "confidence": 0.9,
                },
            ]
        }


async def _seed_data(session: AsyncSession) -> tuple[Creator, ContentItem, Evidence]:
    """Create creator + content item + interaction + evidence for testing."""
    creator = Creator(name="TestCreator", niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()

    ts = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    ci = ContentItem(
        creator_id=creator.id,
        platform="youtube",
        external_id="vid_001",
        title="Battery Test Video",
        content_type=ContentType.VIDEO,
        published_at=ts,
    )
    session.add(ci)
    await session.flush()

    interaction = AudienceInteraction(
        content_item_id=ci.id,
        external_id="cmt_001",
        text="My battery dies in 2 hours! Anyone else?",
        author_handle="viewer1",
        interaction_type=InteractionType.COMMENT,
        posted_at=ts,
    )
    session.add(interaction)
    await session.flush()

    evidence = Evidence(
        source_type="comment",
        source_id="cmt_001",
        source_platform="youtube",
        raw_text="My battery dies in 2 hours! Anyone else?",
        author_handle="viewer1",
        access_method=AccessMethod.OFFICIAL,
        compliance_status=ComplianceStatus.COMPLIANT,
    )
    session.add(evidence)
    await session.flush()

    return creator, ci, evidence


@pytest.mark.asyncio
async def test_pipeline_creates_research_run(clean_db: AsyncSession):
    session = clean_db
    creator, _, _ = await _seed_data(session)
    provider = FakeProvider()
    pipeline = IntelligencePipeline(provider, session)

    run = await pipeline.run(creator.id)

    assert run.status == "completed"
    assert run.creator_id == creator.id
    assert run.completed_at is not None
    assert run.prompt_versions["extraction"] == EXTRACTION_PROMPT_VERSION
    assert run.prompt_versions["topics"] == TOPIC_PROMPT_VERSION
    assert run.model_versions["primary"] == "fake-test-model"


@pytest.mark.asyncio
async def test_pipeline_creates_problem_observations(clean_db: AsyncSession):
    session = clean_db
    creator, _, evidence = await _seed_data(session)
    pipeline = IntelligencePipeline(FakeProvider(), session)

    await pipeline.run(creator.id)

    result = await session.execute(select(ProblemObservation))
    observations = result.scalars().all()

    assert len(observations) == 1
    obs = observations[0]
    assert obs.text == "Viewer has battery issues"
    assert obs.category == "problem"
    assert obs.is_inferred is False
    assert obs.confidence == 0.9
    assert obs.evidence_id == evidence.id
    assert obs.extraction_prompt_version == EXTRACTION_PROMPT_VERSION
    assert obs.model_version == "fake-test-model"


@pytest.mark.asyncio
async def test_pipeline_evidence_fk_chain(clean_db: AsyncSession):
    """Comment → Evidence → ProblemObservation FK chain is intact."""
    session = clean_db
    creator, _, evidence = await _seed_data(session)
    pipeline = IntelligencePipeline(FakeProvider(), session)

    await pipeline.run(creator.id)

    result = await session.execute(
        select(ProblemObservation).where(ProblemObservation.evidence_id == evidence.id)
    )
    obs = result.scalars().all()
    assert len(obs) == 1
    assert obs[0].evidence_id == evidence.id


@pytest.mark.asyncio
async def test_pipeline_stores_topics(clean_db: AsyncSession):
    session = clean_db
    creator, ci, _ = await _seed_data(session)
    pipeline = IntelligencePipeline(FakeProvider(), session)

    await pipeline.run(creator.id)

    await session.refresh(ci)
    assert ci.topics is not None
    assert len(ci.topics) == 1
    assert ci.topics[0]["name"] == "Tech Reviews"


@pytest.mark.asyncio
async def test_pipeline_failure_marks_run_failed(clean_db: AsyncSession):
    session = clean_db
    creator, _, _ = await _seed_data(session)

    class FailingProvider(LLMProvider):
        @property
        def model_name(self) -> str:
            return "failing"

        async def generate_json(self, prompt: str, system: str | None = None) -> dict:
            raise RuntimeError("LLM down")

    pipeline = IntelligencePipeline(FailingProvider(), session)

    with pytest.raises(RuntimeError, match="LLM down"):
        await pipeline.run(creator.id)

    result = await session.execute(
        select(ResearchRun).where(ResearchRun.creator_id == creator.id)
    )
    run = result.scalar_one()
    assert run.status == "failed"
    assert "LLM down" in run.error_message


@pytest.mark.asyncio
async def test_pipeline_no_interactions_still_classifies_topics(clean_db: AsyncSession):
    """Even if no comments exist, topic classification should run."""
    session = clean_db
    creator = Creator(name="NoComments", niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()

    ci = ContentItem(
        creator_id=creator.id,
        platform="youtube",
        external_id="vid_solo",
        title="Solo Video",
        content_type=ContentType.VIDEO,
    )
    session.add(ci)
    await session.flush()

    pipeline = IntelligencePipeline(FakeProvider(), session)
    run = await pipeline.run(creator.id)

    assert run.status == "completed"
    await session.refresh(ci)
    assert ci.topics is not None
