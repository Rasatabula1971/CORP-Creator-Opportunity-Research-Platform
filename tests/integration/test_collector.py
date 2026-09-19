"""Integration tests for AcquisitionCollector against real Postgres."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem
from corp.core.models.creator import Creator
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.workflow import ResearchRun
from corp.workers.acquisition.collector import AcquisitionCollector
from corp.workers.adapters.base import NormalizedContent, SourceAdapter


class FakeAdapter(SourceAdapter):
    """Adapter returning canned NormalizedContent items."""

    def __init__(self, items: list[NormalizedContent] | None = None) -> None:
        self._items = items or self._default_items()

    @property
    def platform(self) -> str:
        return "youtube"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OFFICIAL

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        return self._items

    @staticmethod
    def _default_items() -> list[NormalizedContent]:
        ts = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
        return [
            NormalizedContent(
                source_platform="youtube",
                content_type="video",
                external_id="vid_001",
                text="Test Video Title",
                author="TestChannel",
                timestamp=ts,
                url="https://www.youtube.com/watch?v=vid_001",
                access_method=AccessMethod.OFFICIAL,
                compliance_status=ComplianceStatus.COMPLIANT,
                metadata={
                    "description": "A test video",
                    "view_count": 1000,
                    "like_count": 50,
                    "comment_count": 5,
                },
            ),
            NormalizedContent(
                source_platform="youtube",
                content_type="comment",
                external_id="cmt_001",
                text="Great video! Where can I buy that?",
                author="viewer1",
                timestamp=ts,
                parent_id="vid_001",
                access_method=AccessMethod.OFFICIAL,
                compliance_status=ComplianceStatus.COMPLIANT,
                metadata={"like_count": 3},
            ),
            NormalizedContent(
                source_platform="youtube",
                content_type="reply",
                external_id="reply_001",
                text="Check the link in description!",
                author="TestChannel",
                timestamp=ts,
                parent_id="cmt_001",
                access_method=AccessMethod.OFFICIAL,
                compliance_status=ComplianceStatus.COMPLIANT,
                metadata={"like_count": 1},
            ),
            NormalizedContent(
                source_platform="youtube",
                content_type="caption",
                external_id="caption_vid_001",
                text="Welcome to my channel today we review...",
                parent_id="vid_001",
                access_method=AccessMethod.OFFICIAL,
                compliance_status=ComplianceStatus.COMPLIANT,
            ),
        ]


async def _create_creator(session: AsyncSession) -> Creator:
    creator = Creator(name="TestCreator", niche="tech", discovery_source="manual")
    session.add(creator)
    await session.flush()
    return creator


@pytest.mark.asyncio
async def test_collect_creates_research_run(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)
    adapter = FakeAdapter()
    collector = AcquisitionCollector(adapter, session)

    run = await collector.collect_creator_data("@test", creator.id)

    assert run.status == "completed"
    assert run.creator_id == creator.id
    assert run.completed_at is not None
    assert run.config_snapshot["adapter"] == "youtube"


@pytest.mark.asyncio
async def test_collect_stores_content_items(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)
    collector = AcquisitionCollector(FakeAdapter(), session)

    await collector.collect_creator_data("@test", creator.id)

    result = await session.execute(
        select(ContentItem).where(ContentItem.creator_id == creator.id)
    )
    items = result.scalars().all()
    assert len(items) == 1
    assert items[0].external_id == "vid_001"
    assert items[0].title == "Test Video Title"
    assert items[0].view_count == 1000


@pytest.mark.asyncio
async def test_collect_stores_interactions(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)
    collector = AcquisitionCollector(FakeAdapter(), session)

    await collector.collect_creator_data("@test", creator.id)

    result = await session.execute(select(AudienceInteraction))
    interactions = result.scalars().all()
    assert len(interactions) == 2

    comment = next(i for i in interactions if i.external_id == "cmt_001")
    assert "Where can I buy" in comment.text

    reply = next(i for i in interactions if i.external_id == "reply_001")
    assert reply.parent_id == "cmt_001"


@pytest.mark.asyncio
async def test_collect_creates_evidence_chain(clean_db: AsyncSession):
    session = clean_db
    creator = await _create_creator(session)
    collector = AcquisitionCollector(FakeAdapter(), session)

    run = await collector.collect_creator_data("@test", creator.id)

    result = await session.execute(
        select(Evidence).where(Evidence.research_run_id == run.id)
    )
    evidence_rows = result.scalars().all()

    # 1 video + 1 comment + 1 reply + 1 caption = 4 evidence rows
    assert len(evidence_rows) == 4

    types = {e.source_type for e in evidence_rows}
    assert types == {"video", "comment", "reply", "caption"}

    video_ev = next(e for e in evidence_rows if e.source_type == "video")
    assert video_ev.source_id == "vid_001"
    assert video_ev.access_method == AccessMethod.OFFICIAL


@pytest.mark.asyncio
async def test_collect_matches_question_and_review_interactions_by_parent_id(
    clean_db: AsyncSession,
):
    """_INTERACTION_TYPE_MAP declares "question" and "review" as supported
    interaction types alongside "comment" — a top-level one with a matching
    parent_id must resolve to its ContentItem, not be silently orphaned."""
    session = clean_db
    creator = await _create_creator(session)
    ts = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    items = [
        NormalizedContent(
            source_platform="youtube",
            content_type="video",
            external_id="vid_001",
            text="Test Video Title",
            author="TestChannel",
            timestamp=ts,
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
            metadata={},
        ),
        NormalizedContent(
            source_platform="youtube",
            content_type="question",
            external_id="q_001",
            text="What mic do you use?",
            timestamp=ts,
            parent_id="vid_001",
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
        ),
        NormalizedContent(
            source_platform="youtube",
            content_type="review",
            external_id="rv_001",
            text="Solid product, five stars",
            timestamp=ts,
            parent_id="vid_001",
            access_method=AccessMethod.OFFICIAL,
            compliance_status=ComplianceStatus.COMPLIANT,
        ),
    ]
    collector = AcquisitionCollector(FakeAdapter(items), session)

    run = await collector.collect_creator_data("@test", creator.id)

    assert run.stats["extra"]["orphaned_interactions"] == 0
    assert run.stats["extra"]["interactions"] == 2

    result = await session.execute(select(AudienceInteraction))
    interactions = {i.external_id: i for i in result.scalars().all()}
    assert set(interactions) == {"q_001", "rv_001"}


@pytest.mark.asyncio
async def test_collect_idempotent(clean_db: AsyncSession):
    """Running collection twice should not create duplicate ContentItems."""
    session = clean_db
    creator = await _create_creator(session)
    adapter = FakeAdapter()
    collector = AcquisitionCollector(adapter, session)

    await collector.collect_creator_data("@test", creator.id)
    await collector.collect_creator_data("@test", creator.id)

    result = await session.execute(
        select(ContentItem).where(ContentItem.creator_id == creator.id)
    )
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_collect_failure_marks_run_failed(clean_db: AsyncSession):
    """If the adapter raises, the ResearchRun is marked failed."""
    session = clean_db
    creator = await _create_creator(session)

    class FailingAdapter(FakeAdapter):
        async def collect(self, identifier: str) -> list[NormalizedContent]:
            raise RuntimeError("API exploded")

    collector = AcquisitionCollector(FailingAdapter(), session)

    with pytest.raises(RuntimeError, match="API exploded"):
        await collector.collect_creator_data("@test", creator.id)

    result = await session.execute(
        select(ResearchRun).where(ResearchRun.creator_id == creator.id)
    )
    run = result.scalar_one()
    assert run.status == "failed"
    assert "API exploded" in run.error_message
