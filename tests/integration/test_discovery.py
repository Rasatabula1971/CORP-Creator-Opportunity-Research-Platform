"""Slice 7 — niche discovery light, one source. Real Postgres, faked adapter.

The live-source test at the bottom is skipped unless CORP_LIVE_TESTS=1.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence
from corp.core.models.research_query import ResearchQuery, ResearchQueryStatus
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.core.research.ledger import find_queries
from corp.workers.acquisition.discovery import NicheDiscoveryCollector
from corp.workers.adapters.base import NormalizedContent, SourceAdapter
from corp.workers.intelligence.runs import start_run


def _item(ext_id: str, text: str, content_type: str = "post") -> NormalizedContent:
    return NormalizedContent(
        source_platform="fake",
        content_type=content_type,
        external_id=ext_id,
        text=text,
        author=f"u_{ext_id}",
        timestamp=datetime(2026, 9, 1, tzinfo=UTC),
        url=f"https://fake.example/{ext_id}",
        access_method=AccessMethod.OPEN,
        compliance_status=ComplianceStatus.VERIFY,
    )


class FakeAdapter(SourceAdapter):
    def __init__(self, items: list[NormalizedContent] | None = None, fail: bool = False):
        self._items = items or []
        self._fail = fail
        self.calls: list[str] = []

    @property
    def platform(self) -> str:
        return "fake"

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.VERIFY

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        self.calls.append(identifier)
        if self._fail:
            raise RuntimeError("source unreachable")
        return list(self._items)


THREE = [
    _item("p1", "My espresso machine leaks, what gasket do I need?"),
    _item("p2", "Best grinder under 200?"),
    _item("c1", "Same problem here, replaced the group gasket", content_type="comment"),
]


async def _campaign(session: AsyncSession) -> Campaign:
    campaign = Campaign(name="Discovery Test")
    session.add(campaign)
    await session.flush()
    return campaign


@pytest.mark.asyncio
async def test_discovery_creates_niche_discovery_run_under_campaign(
    clean_db: AsyncSession, tmp_path: Path
):
    session = clean_db
    campaign = await _campaign(session)
    adapter = FakeAdapter(THREE)

    run = await NicheDiscoveryCollector(adapter, session, str(tmp_path)).discover(
        campaign.id, "r/espresso"
    )

    assert adapter.calls == ["r/espresso"]
    assert run.run_type == RunType.NICHE_DISCOVERY.value
    assert run.campaign_id == campaign.id
    assert run.creator_id is None
    assert run.niche_id is None
    assert run.scope == RunScope.NICHE.value
    assert run.status == "completed"
    assert run.config_snapshot == {
        "pipeline": "niche_discovery",
        "source": "fake",
        "query": "r/espresso",
    }
    assert run.stats["succeeded"] == 3
    assert run.stats["extra"] == {"results_seen": 3, "new_results": 3, "duplicate_results": 0}


@pytest.mark.asyncio
async def test_discovery_persists_evidence_with_run_provenance(
    clean_db: AsyncSession, tmp_path: Path
):
    session = clean_db
    campaign = await _campaign(session)
    run = await NicheDiscoveryCollector(FakeAdapter(THREE), session, str(tmp_path)).discover(
        campaign.id, "r/espresso"
    )

    rows = (
        await session.execute(select(Evidence).where(Evidence.research_run_id == run.id))
    ).scalars().all()
    assert len(rows) == 3
    by_id = {e.source_id: e for e in rows}
    assert by_id["p1"].raw_text.startswith("My espresso machine leaks")
    assert by_id["p1"].source_type == "post"
    assert by_id["c1"].source_type == "comment"
    assert by_id["p1"].source_platform == "fake"
    assert by_id["p1"].author_handle == "u_p1"
    assert by_id["p1"].source_url == "https://fake.example/p1"
    assert by_id["p1"].access_method == AccessMethod.OPEN
    assert by_id["p1"].compliance_status == ComplianceStatus.VERIFY


@pytest.mark.asyncio
async def test_discovery_records_query_with_counts(clean_db: AsyncSession, tmp_path: Path):
    session = clean_db
    campaign = await _campaign(session)
    run = await NicheDiscoveryCollector(FakeAdapter(THREE), session, str(tmp_path)).discover(
        campaign.id, "r/espresso"
    )

    queries = await find_queries(session, research_run_id=run.id)
    assert len(queries) == 1
    q = queries[0]
    assert q.source == "fake"
    assert q.query == "r/espresso"
    assert q.status == ResearchQueryStatus.SUCCEEDED
    assert (q.results_seen, q.new_results, q.duplicate_results) == (3, 3, 0)
    assert q.error is None


@pytest.mark.asyncio
async def test_second_run_same_query_counts_duplicates_adds_no_evidence(
    clean_db: AsyncSession, tmp_path: Path
):
    """Invariant 8: previously researched material is not blindly re-stored."""
    session = clean_db
    campaign = await _campaign(session)
    collector = NicheDiscoveryCollector(FakeAdapter(THREE), session, str(tmp_path))
    first = await collector.discover(campaign.id, "r/espresso")

    fresh = [*THREE, _item("p3", "New post since last time")]
    second = await NicheDiscoveryCollector(FakeAdapter(fresh), session, str(tmp_path)).discover(
        campaign.id, "r/espresso"
    )

    total = (await session.execute(select(Evidence))).scalars().all()
    assert len(total) == 4  # 3 from first + only the 1 genuinely new one

    q2 = (await find_queries(session, research_run_id=second.id))[0]
    assert (q2.results_seen, q2.new_results, q2.duplicate_results) == (4, 1, 3)
    assert second.stats["skipped"] == 3
    assert second.status == "completed"

    history = await find_queries(session, source="fake", query="r/espresso")
    assert {h.research_run_id for h in history} == {first.id, second.id}


@pytest.mark.asyncio
async def test_discovery_writes_archive_and_records_reference(
    clean_db: AsyncSession, tmp_path: Path
):
    session = clean_db
    campaign = await _campaign(session)
    run = await NicheDiscoveryCollector(FakeAdapter(THREE), session, str(tmp_path)).discover(
        campaign.id, "r/Home Espresso!"
    )

    q = (await find_queries(session, research_run_id=run.id))[0]
    assert q.archive_reference == f"discovery/{run.id}/fake__r_home_espresso.jsonl"

    archived = tmp_path / q.archive_reference
    assert archived.is_file()
    lines = [json.loads(line) for line in archived.read_text(encoding="utf-8").splitlines()]
    assert [line["external_id"] for line in lines] == ["p1", "p2", "c1"]
    assert lines[0]["text"].startswith("My espresso machine leaks")


@pytest.mark.asyncio
async def test_discovery_empty_result_completes(clean_db: AsyncSession, tmp_path: Path):
    """§19: INSUFFICIENT_EVIDENCE is a valid result — an empty source is not a failure."""
    session = clean_db
    campaign = await _campaign(session)
    run = await NicheDiscoveryCollector(FakeAdapter([]), session, str(tmp_path)).discover(
        campaign.id, "r/empty"
    )
    assert run.status == "completed"
    q = (await find_queries(session, research_run_id=run.id))[0]
    assert (q.results_seen, q.new_results, q.duplicate_results) == (0, 0, 0)


@pytest.mark.asyncio
async def test_discovery_unknown_campaign_raises(clean_db: AsyncSession, tmp_path: Path):
    with pytest.raises(ValueError, match="Campaign not found"):
        await NicheDiscoveryCollector(FakeAdapter(THREE), clean_db, str(tmp_path)).discover(
            "does-not-exist", "r/espresso"
        )
    assert (await clean_db.execute(select(ResearchRun))).scalars().all() == []


@pytest.mark.asyncio
async def test_adapter_failure_records_failed_query_and_fails_run(
    clean_db: AsyncSession, tmp_path: Path
):
    """A failed search is still research memory: the run and the FAILED ledger
    row must come back to the caller (who commits), not be lost to a rollback
    behind a raised exception. Found live: Reddit 403 → everything rolled back."""
    session = clean_db
    campaign = await _campaign(session)
    returned = await NicheDiscoveryCollector(
        FakeAdapter(fail=True), session, str(tmp_path)
    ).discover(campaign.id, "r/espresso")

    assert returned.status == "failed"
    run = (await session.execute(select(ResearchRun))).scalar_one()
    assert run.id == returned.id
    assert "source unreachable" in run.error_message
    assert run.completed_at is not None
    q = (await session.execute(select(ResearchQuery))).scalar_one()
    assert q.status == ResearchQueryStatus.FAILED
    assert q.error == "source unreachable"
    assert q.research_run_id == run.id
    assert (await session.execute(select(Evidence))).scalars().all() == []


@pytest.mark.asyncio
async def test_provenance_chain_evidence_to_campaign(clean_db: AsyncSession, tmp_path: Path):
    """Acceptance: provenance can be traced. Evidence → run → campaign, and
    evidence → run → query, without any join table beyond what exists."""
    session = clean_db
    campaign = await _campaign(session)
    run = await NicheDiscoveryCollector(FakeAdapter(THREE[:1]), session, str(tmp_path)).discover(
        campaign.id, "r/espresso"
    )

    evidence = (await session.execute(select(Evidence))).scalar_one()
    linked_run = await session.get(ResearchRun, evidence.research_run_id)
    assert linked_run.id == run.id
    assert (await session.get(Campaign, linked_run.campaign_id)).name == "Discovery Test"
    await session.refresh(linked_run, ["research_queries"])
    assert [q.query for q in linked_run.research_queries] == ["r/espresso"]


@pytest.mark.asyncio
async def test_start_run_defaults_unchanged_for_existing_call_sites(clean_db: AsyncSession):
    """Regression for the start_run extension: existing callers pass none of the
    new kwargs and must get exactly what they got before."""
    run = await start_run(clean_db, pipeline="collect", creator_id=None)
    assert run.run_type == RunType.CREATOR_RESEARCH.value
    assert run.campaign_id is None
    assert run.niche_id is None
    assert run.scope == RunScope.CROSS.value


@pytest.mark.skipif(not os.environ.get("CORP_LIVE_TESTS"), reason="set CORP_LIVE_TESTS=1")
@pytest.mark.asyncio
async def test_live_youtube_search_discovery(clean_db: AsyncSession, tmp_path: Path):
    """Live source: yt-dlp's native search. Reddit's unauthenticated .json feed
    returns 403 Blocked as of 2026-09-14 (see docs/DECISIONS/0007), so the live
    approved source for discovery-light is YouTube search via yt-dlp."""
    from corp.workers.adapters.registry import build_adapter

    session = clean_db
    campaign = await _campaign(session)
    run = await NicheDiscoveryCollector(build_adapter("youtube"), session, str(tmp_path)).discover(
        campaign.id, "ytsearch3:espresso machine leaking from group head"
    )
    assert run.status == "completed"
    q = (await find_queries(session, research_run_id=run.id))[0]
    assert q.source == "youtube"
    assert q.results_seen > 0
    assert q.new_results == q.results_seen
    assert (tmp_path / q.archive_reference).is_file()
    types = {
        e.source_type
        for e in (
            await session.execute(select(Evidence).where(Evidence.research_run_id == run.id))
        ).scalars()
    }
    assert "video" in types
    assert "profile" not in types  # a search spans channels; no creator profile
