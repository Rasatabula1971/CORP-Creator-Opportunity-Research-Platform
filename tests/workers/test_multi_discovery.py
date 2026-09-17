"""Tests for multi-source niche discovery — all DB + HTTP calls mocked."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.acquisition.multi_discovery import (
    NICHE_PLATFORMS,
    MultiSourceDiscovery,
    _to_evidence,
)
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter
from corp.workers.adapters.health import SourceHealthTracker

# ── Fixtures ─────────────────────────────────────────────────────────


class FakeAdapter(SourceAdapter):
    def __init__(self, name: str, items: list[NormalizedContent] | None = None, error: Exception | None = None):
        self._name = name
        self._items = items or []
        self._error = error
        self._closed = False

    @property
    def platform(self) -> str:
        return self._name

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.NICHE

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        if self._error:
            raise self._error
        return self._items

    async def close(self) -> None:
        self._closed = True


def _make_item(platform: str, ext_id: str, text: str = "test") -> NormalizedContent:
    return NormalizedContent(
        source_platform=platform,
        content_type="story",
        external_id=ext_id,
        text=text,
        access_method=AccessMethod.OPEN,
        compliance_status=ComplianceStatus.COMPLIANT,
    )


@pytest.fixture
def mock_session():
    session = AsyncMock()
    campaign = MagicMock()
    campaign.id = "camp-1"
    session.get = AsyncMock(return_value=campaign)

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def tracker(tmp_path):
    return SourceHealthTracker(tmp_path)


# ── _to_evidence helper ─────────────────────────────────────────────


def test_to_evidence():
    item = _make_item("hackernews", "hn_001", "Test story text")
    ev = _to_evidence(item, "run-123")
    assert ev.source_platform == "hackernews"
    assert ev.source_id == "hn_001"
    assert ev.raw_text == "Test story text"
    assert ev.research_run_id == "run-123"


# ── NICHE_PLATFORMS includes expected adapters ───────────────────────


def test_niche_platforms_includes_expected():
    assert "hackernews" in NICHE_PLATFORMS
    assert "wikipedia" in NICHE_PLATFORMS
    assert "googletrends" in NICHE_PLATFORMS
    assert "appstore" in NICHE_PLATFORMS
    assert "stackexchange" in NICHE_PLATFORMS
    assert "searchdemand" in NICHE_PLATFORMS
    assert "amazon_reviews" in NICHE_PLATFORMS
    assert "marketplace" in NICHE_PLATFORMS


def test_niche_platforms_excludes_creator_bound():
    assert "youtube" not in NICHE_PLATFORMS
    assert "reddit" not in NICHE_PLATFORMS
    assert "tiktok" not in NICHE_PLATFORMS


# ── Multi-source discovery ───────────────────────────────────────────


@patch("corp.workers.acquisition.multi_discovery.mirror_evidence", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.record_query", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.validate_run_type")
@patch("corp.workers.acquisition.multi_discovery.finish_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.start_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.build_adapter")
async def test_discover_fans_out(
    mock_build, mock_start, mock_finish, mock_validate, mock_record, mock_mirror,
    mock_session, tracker, tmp_path,
):
    run = MagicMock()
    run.id = "run-1"
    mock_start.return_value = run
    mock_finish.return_value = run

    items_hn = [_make_item("hackernews", "hn1")]
    items_wiki = [_make_item("wikipedia", "wiki1"), _make_item("wikipedia", "wiki2")]

    def build_side_effect(platform, cfg=None):
        if platform == "hackernews":
            return FakeAdapter("hackernews", items_hn)
        if platform == "wikipedia":
            return FakeAdapter("wikipedia", items_wiki)
        return FakeAdapter(platform, [])

    mock_build.side_effect = build_side_effect

    disco = MultiSourceDiscovery(
        mock_session,
        str(tmp_path),
        platforms=("hackernews", "wikipedia"),
        health_tracker=tracker,
    )
    result = await disco.discover("camp-1", "python")

    assert mock_start.called
    assert mock_finish.called
    assert mock_record.call_count == 2

    stats = mock_finish.call_args[0][2]
    # Two sources succeeded (stats count sources, not items).
    assert stats.succeeded == 2
    assert stats.extra["total_sources_ok"] == 2
    assert stats.extra["total_new_items"] == 3
    assert stats.extra["total_items"] == 3


@patch("corp.workers.acquisition.multi_discovery.mirror_evidence", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.record_query", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.validate_run_type")
@patch("corp.workers.acquisition.multi_discovery.finish_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.start_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.build_adapter")
async def test_skips_disconnected_source(
    mock_build, mock_start, mock_finish, mock_validate, mock_record, mock_mirror,
    mock_session, tracker, tmp_path,
):
    run = MagicMock()
    run.id = "run-2"
    mock_start.return_value = run
    mock_finish.return_value = run

    for _ in range(6):
        tracker.record_failure("hackernews", RuntimeError("down"))

    mock_build.return_value = FakeAdapter("wikipedia", [_make_item("wikipedia", "w1")])

    disco = MultiSourceDiscovery(
        mock_session,
        str(tmp_path),
        platforms=("hackernews", "wikipedia"),
        health_tracker=tracker,
    )
    await disco.discover("camp-1", "python")

    stats = mock_finish.call_args[0][2]
    assert stats.extra["per_source"]["hackernews"]["status"] == "skipped"
    assert stats.extra["per_source"]["hackernews"]["reason"] == "disconnected"
    assert stats.extra["per_source"]["wikipedia"]["status"] == "ok"


@patch("corp.workers.acquisition.multi_discovery.mirror_evidence", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.record_query", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.validate_run_type")
@patch("corp.workers.acquisition.multi_discovery.finish_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.start_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.build_adapter")
async def test_source_failure_continues_run(
    mock_build, mock_start, mock_finish, mock_validate, mock_record, mock_mirror,
    mock_session, tracker, tmp_path,
):
    run = MagicMock()
    run.id = "run-3"
    mock_start.return_value = run
    mock_finish.return_value = run

    def build_side_effect(platform, cfg=None):
        if platform == "hackernews":
            return FakeAdapter("hackernews", error=RuntimeError("503 timeout"))
        return FakeAdapter("wikipedia", [_make_item("wikipedia", "w1")])

    mock_build.side_effect = build_side_effect

    disco = MultiSourceDiscovery(
        mock_session,
        str(tmp_path),
        platforms=("hackernews", "wikipedia"),
        health_tracker=tracker,
    )
    await disco.discover("camp-1", "python")

    stats = mock_finish.call_args[0][2]
    assert stats.extra["per_source"]["hackernews"]["status"] == "failed"
    assert stats.extra["per_source"]["wikipedia"]["status"] == "ok"
    # One source failed, one succeeded (source-level accounting).
    assert stats.failed == 1
    assert stats.succeeded == 1
    assert stats.extra["total_sources_failed"] == 1
    assert stats.extra["total_sources_ok"] == 1

    assert tracker.get_record("hackernews").total_failures == 1
    assert tracker.get_record("wikipedia").total_successes == 1


@patch("corp.workers.acquisition.multi_discovery.mirror_evidence", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.record_query", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.validate_run_type")
@patch("corp.workers.acquisition.multi_discovery.finish_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.start_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.build_adapter")
async def test_failure_rate_reflects_sources_not_items(
    mock_build, mock_start, mock_finish, mock_validate, mock_record, mock_mirror,
    mock_session, tracker, tmp_path,
):
    # Three sources fail; one chatty source returns many items. The run's
    # failure_rate must reflect the sources (3/4 = 0.75), not be diluted by the
    # survivor's item count — the whole point of counting sources.
    run = MagicMock()
    run.id = "run-fr"
    mock_start.return_value = run
    mock_finish.return_value = run

    many = [_make_item("wikipedia", f"w{i}") for i in range(20)]

    def build_side_effect(platform, cfg=None):
        if platform == "wikipedia":
            return FakeAdapter("wikipedia", many)
        return FakeAdapter(platform, error=RuntimeError("down"))

    mock_build.side_effect = build_side_effect

    disco = MultiSourceDiscovery(
        mock_session,
        str(tmp_path),
        platforms=("hackernews", "appstore", "stackexchange", "wikipedia"),
        health_tracker=tracker,
    )
    await disco.discover("camp-1", "python")

    stats = mock_finish.call_args[0][2]
    assert stats.succeeded == 1        # one source ok
    assert stats.failed == 3           # three sources down
    assert stats.attempted == 4
    assert stats.failure_rate == 0.75  # sources, not diluted by 20 items
    assert stats.extra["total_new_items"] == 20


@patch("corp.workers.acquisition.multi_discovery.mirror_evidence", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.record_query", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.validate_run_type")
@patch("corp.workers.acquisition.multi_discovery.finish_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.start_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.build_adapter")
async def test_deduplicates_evidence(
    mock_build, mock_start, mock_finish, mock_validate, mock_record, mock_mirror,
    mock_session, tracker, tmp_path,
):
    run = MagicMock()
    run.id = "run-4"
    mock_start.return_value = run
    mock_finish.return_value = run

    dupe_result = MagicMock()
    dupe_result.scalar_one_or_none.return_value = "existing-id"
    fresh_result = MagicMock()
    fresh_result.scalar_one_or_none.return_value = None

    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return dupe_result
        return fresh_result

    mock_session.execute = execute_side_effect

    mock_build.return_value = FakeAdapter(
        "hackernews",
        [_make_item("hackernews", "hn1"), _make_item("hackernews", "hn2")],
    )

    disco = MultiSourceDiscovery(
        mock_session,
        str(tmp_path),
        platforms=("hackernews",),
        health_tracker=tracker,
    )
    await disco.discover("camp-1", "python")

    stats = mock_finish.call_args[0][2]
    # One source succeeded; the dedup is an item-level count, not a skipped source.
    assert stats.succeeded == 1
    assert stats.extra["total_new_items"] == 1
    assert stats.extra["total_duplicate_items"] == 1


async def test_discover_unknown_campaign(tmp_path, tracker):
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    disco = MultiSourceDiscovery(session, str(tmp_path), health_tracker=tracker)
    with pytest.raises(ValueError, match="Campaign not found"):
        await disco.discover("bad-id", "python")


# ── Health summary ───────────────────────────────────────────────────


def test_health_summary(tracker):
    tracker.record_success("hackernews")
    tracker.record_failure("appstore", RuntimeError("fail"))

    disco_tracker = tracker
    s = disco_tracker.summary()
    assert "hackernews" in s
    assert "appstore" in s


# ── Archive ──────────────────────────────────────────────────────────


@patch("corp.workers.acquisition.multi_discovery.mirror_evidence", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.record_query", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.validate_run_type")
@patch("corp.workers.acquisition.multi_discovery.finish_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.start_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.build_adapter")
async def test_archive_written(
    mock_build, mock_start, mock_finish, mock_validate, mock_record, mock_mirror,
    mock_session, tracker, tmp_path,
):
    run = MagicMock()
    run.id = "run-archive"
    mock_start.return_value = run
    mock_finish.return_value = run

    mock_build.return_value = FakeAdapter(
        "hackernews", [_make_item("hackernews", "hn1")]
    )

    disco = MultiSourceDiscovery(
        mock_session,
        str(tmp_path),
        platforms=("hackernews",),
        health_tracker=tracker,
    )
    await disco.discover("camp-1", "python")

    stats = mock_finish.call_args[0][2]
    archive_ref = stats.extra.get("archive_reference")
    assert archive_ref is not None
    archive_path = tmp_path / archive_ref
    assert archive_path.exists()


# ── All sources skipped ──────────────────────────────────────────────


@patch("corp.workers.acquisition.multi_discovery.mirror_evidence", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.record_query", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.validate_run_type")
@patch("corp.workers.acquisition.multi_discovery.finish_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.start_run", new_callable=AsyncMock)
@patch("corp.workers.acquisition.multi_discovery.build_adapter")
async def test_all_sources_skipped_is_a_failed_run(
    mock_build: MagicMock,
    mock_start: AsyncMock,
    mock_finish: AsyncMock,
    mock_validate: MagicMock,
    mock_record: AsyncMock,
    mock_mirror: AsyncMock,
    mock_session: AsyncMock,
    tracker: SourceHealthTracker,
    tmp_path: Path,
) -> None:
    # One source is circuit-broken, the other cannot be built. Nothing was
    # attempted, so 0/0 must not read as a completed run that did no work.
    from corp.workers.intelligence.runs import resolve_status

    run = MagicMock()
    run.id = "run-none"
    mock_start.return_value = run
    mock_finish.return_value = run

    for _ in range(6):
        tracker.record_failure("hackernews", RuntimeError("down"))
    mock_build.side_effect = RuntimeError("no api key")

    disco = MultiSourceDiscovery(
        mock_session,
        str(tmp_path),
        platforms=("hackernews", "wikipedia"),
        health_tracker=tracker,
    )
    await disco.discover("camp-1", "python")

    stats = mock_finish.call_args[0][2]
    assert stats.extra["total_sources_attempted"] == 0
    assert stats.extra["total_sources_skipped"] == 2
    assert stats.attempted == stats.failed == 1
    assert resolve_status(stats, 0.5) == "failed"
    assert "hackernews=disconnected" in stats.last_error
    assert "wikipedia=build_error: no api key" in stats.last_error
    assert mock_record.call_count == 0
