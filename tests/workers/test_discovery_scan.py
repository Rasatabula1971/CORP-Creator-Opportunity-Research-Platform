"""Tests for the autonomous discovery crawler (CORP1 Step 1 on a timer)."""

import asyncio
from typing import Any

import pytest

from corp.core.models.campaign import Campaign, CampaignStatus
from corp.workers.scheduler.discovery_scan import (
    AUTONOMOUS_CAMPAIGN_NAME,
    AUTONOMOUS_CAMPAIGN_SLUG,
    DiscoveryDeferredError,
    DiscoveryHandle,
    DiscoveryScanScheduler,
    get_or_create_autonomous_campaign,
    run_discovery_pass,
)


class _FakeRun:
    def __init__(self, run_id: str = "run-1", status: str = "completed") -> None:
        self.id = run_id
        self.status = status


class _FakeProvider:
    model_name = "fake-model"

    async def generate_json(self, prompt: str, system: str | None = None, **kw: Any) -> dict:
        return {}


async def _noop() -> None:
    return None


@pytest.fixture
def patched_pipeline(monkeypatch):
    """Replace the drill engine and qualifier so these tests exercise the
    pass's own orchestration, not the recursive LLM pipeline."""
    calls: dict[str, list] = {"discover": [], "qualify": []}

    class _FakeDiscovery:
        def __init__(self, session, provider, rules_path):
            self.session = session

        async def discover(self, campaign_id: str, topic: str):
            calls["discover"].append((campaign_id, topic))
            if topic == "explode":
                raise RuntimeError("connect to postgresql://corp:hunter2@db.internal failed")
            return _FakeRun(run_id=f"run-{topic}")

    class _FakeQualifier:
        def __init__(self, session, rules_path):
            pass

        async def qualify_campaign(self, campaign_id: str):
            calls["qualify"].append(campaign_id)
            return _FakeRun(run_id="qualify")

    monkeypatch.setattr(
        "corp.workers.scheduler.discovery_scan.RecursiveNicheDiscovery", _FakeDiscovery
    )
    monkeypatch.setattr(
        "corp.workers.scheduler.discovery_scan.NicheQualifier", _FakeQualifier
    )
    return calls


# ── The standing campaign ────────────────────────────────────────────


async def test_autonomous_campaign_is_created_once(clean_db):
    first = await get_or_create_autonomous_campaign(clean_db)
    assert first.name == AUTONOMOUS_CAMPAIGN_NAME
    assert first.status == CampaignStatus.ACTIVE
    second = await get_or_create_autonomous_campaign(clean_db)
    assert second.id == first.id, "a second pass must reuse the campaign, not fork one"


async def test_a_same_named_human_campaign_is_never_adopted(clean_db):
    """A person is free to create their own campaign named "Autonomous
    discovery" (or any casing of it) for unrelated work. Matching it by
    name here would silently repurpose it -- and everything already in
    it -- as the standing target for every future unattended pass. A
    pre-existing row without the slug (e.g. from before this column
    existed) is a one-time migration-time backfill, not a runtime
    lookup -- see migration 8fb35dc16e35."""
    human = Campaign(name=AUTONOMOUS_CAMPAIGN_NAME.upper())
    clean_db.add(human)
    await clean_db.flush()

    found = await get_or_create_autonomous_campaign(clean_db)

    assert found.id != human.id
    assert found.slug == AUTONOMOUS_CAMPAIGN_SLUG
    assert human.slug is None, "the human's campaign must be left untouched"


async def test_losing_the_slug_race_returns_the_winners_row(clean_db, monkeypatch):
    """Audit fix: two near-simultaneous autonomous passes must not each
    find the campaign missing and insert their own copy. This reproduces
    the actual race outcome against real Postgres: a rival row is already
    committed under the unique slug (via a separate, already-closed
    session/connection — no two transactions are ever open at once here,
    so this cannot deadlock), but our session's own initial lookups are
    forced to behave as they would have during the actual race window —
    both missing it — so get_or_create_autonomous_campaign proceeds to
    INSERT and must recover from the real IntegrityError that follows."""
    from tests.conftest import async_test_session

    winner = Campaign(
        name="pre-existing row from the other session",
        slug=AUTONOMOUS_CAMPAIGN_SLUG,
        status=CampaignStatus.ACTIVE,
    )
    async with async_test_session() as rival:
        rival.add(winner)
        await rival.commit()

    real_execute = clean_db.execute
    calls = {"n": 0}

    async def execute_first_lookup_as_a_miss(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:

            class _EmptyResult:
                def scalar_one_or_none(self) -> None:
                    return None

            return _EmptyResult()
        return await real_execute(*args, **kwargs)

    monkeypatch.setattr(clean_db, "execute", execute_first_lookup_as_a_miss)

    found = await get_or_create_autonomous_campaign(clean_db)

    assert found.id == winner.id
    from sqlalchemy import func, select

    count = (
        await clean_db.execute(
            select(func.count()).select_from(Campaign).where(
                Campaign.slug == AUTONOMOUS_CAMPAIGN_SLUG
            )
        )
    ).scalar_one()
    assert count == 1


# ── User-supplied topics: the alternate entry point ──────────────────


async def test_supplied_topics_skip_the_scan_and_drill_directly(clean_db, patched_pipeline):
    stats = await run_discovery_pass(
        clean_db, _FakeProvider(), topics=["suspension setup", "tyre compounds"]
    )
    assert stats.topics_drilled == 2
    assert [t for _, t in patched_pipeline["discover"]] == [
        "suspension setup",
        "tyre compounds",
    ]
    assert all(t["reason"] == "user_supplied" for t in stats.topics)


async def test_supplied_topics_are_normalised_and_blanks_dropped(clean_db, patched_pipeline):
    stats = await run_discovery_pass(
        clean_db, _FakeProvider(), topics=["  Woodworking  ", "", "   "]
    )
    assert [t for _, t in patched_pipeline["discover"]] == ["woodworking"]
    assert stats.topics_selected == 1


async def test_supplied_topics_ignore_the_registry_window(clean_db, patched_pipeline):
    """Asking for a niche by hand must work even if it was just researched
    — otherwise 'ask for a niche' silently does nothing."""
    from datetime import UTC, datetime, timedelta

    from corp.core.models.niche import Niche

    clean_db.add(
        Niche(
            canonical_name="woodworking",
            last_researched_at=datetime.now(UTC),
            next_recheck_at=datetime.now(UTC) + timedelta(days=90),
        )
    )
    await clean_db.flush()

    stats = await run_discovery_pass(clean_db, _FakeProvider(), topics=["woodworking"])
    assert stats.topics_drilled == 1


async def test_pass_attaches_to_an_explicit_campaign(clean_db, patched_pipeline):
    campaign = Campaign(name="My campaign")
    clean_db.add(campaign)
    await clean_db.flush()

    stats = await run_discovery_pass(
        clean_db, _FakeProvider(), topics=["baking"], campaign_id=campaign.id
    )
    assert stats.campaign_id == campaign.id
    assert patched_pipeline["discover"] == [(campaign.id, "baking")]


# ── Failure containment ──────────────────────────────────────────────


async def test_one_failing_topic_does_not_sink_the_pass(clean_db, patched_pipeline):
    stats = await run_discovery_pass(
        clean_db, _FakeProvider(), topics=["baking", "explode", "yoga"]
    )
    assert stats.topics_drilled == 2
    assert stats.topics_failed == 1
    failed = [t for t in stats.topics if t["status"] == "failed"]
    assert len(failed) == 1
    # The surviving topics were still qualified.
    assert stats.qualified is True


async def test_a_failed_topics_error_never_echoes_the_exception(clean_db, patched_pipeline):
    """This dict flows into the job's result (GET /jobs/{job_id}), so an
    adapter/connection exception's own text — which can carry credentials,
    hostnames, or filesystem paths — must never reach it (same rule
    /discovery/status already follows; see routes_ops.py)."""
    stats = await run_discovery_pass(
        clean_db, _FakeProvider(), topics=["baking", "explode", "yoga"]
    )
    [failed] = [t for t in stats.topics if t["status"] == "failed"]
    assert failed["error"] == "drilling this topic failed; details in the server log"
    dumped = repr(stats.as_dict())
    assert "hunter2" not in dumped and "db.internal" not in dumped


async def test_qualification_failure_leaves_the_drilled_niches(clean_db, monkeypatch):
    class _FakeDiscovery:
        def __init__(self, *a, **kw):
            pass

        async def discover(self, campaign_id: str, topic: str):
            return _FakeRun()

    class _BrokenQualifier:
        def __init__(self, *a, **kw):
            pass

        async def qualify_campaign(self, campaign_id: str):
            raise RuntimeError("qualification exploded")

    monkeypatch.setattr(
        "corp.workers.scheduler.discovery_scan.RecursiveNicheDiscovery", _FakeDiscovery
    )
    monkeypatch.setattr(
        "corp.workers.scheduler.discovery_scan.NicheQualifier", _BrokenQualifier
    )
    stats = await run_discovery_pass(clean_db, _FakeProvider(), topics=["baking"])
    assert stats.topics_drilled == 1
    assert stats.qualified is False


async def test_a_scan_that_finds_nothing_spends_nothing(clean_db, patched_pipeline, monkeypatch):
    """Everything in the catalogue still inside its 90-day window: the pass
    must stop before the drill engine, not qualify an untouched campaign."""

    class _EmptyScanner:
        def __init__(self, *a, **kw):
            pass

        async def scan(self, limit=None):
            from corp.workers.intelligence.trend_scan import TrendScanStats

            return [], TrendScanStats(catalogue=10, registry_fresh=10)

    monkeypatch.setattr("corp.workers.scheduler.discovery_scan.TrendScanner", _EmptyScanner)
    stats = await run_discovery_pass(clean_db, _FakeProvider())
    assert stats.topics_selected == 0
    assert stats.topics_drilled == 0
    assert stats.qualified is False
    assert patched_pipeline["discover"] == []
    assert patched_pipeline["qualify"] == []
    assert stats.scan["registry_fresh"] == 10


async def test_the_scan_path_drills_what_the_scanner_returns(
    clean_db, patched_pipeline, monkeypatch
):
    class _Scanner:
        def __init__(self, *a, **kw):
            pass

        async def scan(self, limit=None):
            from corp.workers.intelligence.trend_scan import SeedTopic, TrendScanStats

            seeds = [SeedTopic("woodworking", 80.0, "trends_momentum")]
            return seeds, TrendScanStats(catalogue=1, scored=1, selected=1)

    monkeypatch.setattr("corp.workers.scheduler.discovery_scan.TrendScanner", _Scanner)
    stats = await run_discovery_pass(clean_db, _FakeProvider())
    assert [t for _, t in patched_pipeline["discover"]] == ["woodworking"]
    assert stats.topics[0]["momentum"] == 80.0
    assert stats.topics[0]["reason"] == "trends_momentum"
    assert stats.qualified is True


async def test_qualify_runs_once_for_the_whole_pass(clean_db, patched_pipeline):
    await run_discovery_pass(clean_db, _FakeProvider(), topics=["a", "b", "c"])
    assert len(patched_pipeline["qualify"]) == 1, "ranking must see the full field"


# ── Scheduler ────────────────────────────────────────────────────────


async def test_scheduler_skips_when_a_campaign_job_is_running(clean_db, patched_pipeline):
    built = False

    async def factory():
        nonlocal built
        built = True
        return DiscoveryHandle(_FakeProvider(), None, _noop)

    sched = DiscoveryScanScheduler(
        lambda: clean_db, factory, is_busy=lambda: True
    )
    await sched._tick()
    assert built is False, "a busy console must stop the tick before it spends anything"
    assert sched._consecutive_failures == 0


async def test_scheduler_defers_without_counting_a_failure(clean_db):
    async def factory():
        raise DiscoveryDeferredError("every LLM provider is in cooldown")

    sched = DiscoveryScanScheduler(lambda: clean_db, factory)
    await sched._tick()
    assert sched._consecutive_failures == 0


async def test_scheduler_skips_when_no_provider_is_configured(clean_db):
    async def factory():
        return None

    sched = DiscoveryScanScheduler(lambda: clean_db, factory)
    await sched._tick()
    assert sched._consecutive_failures == 0


async def test_a_failing_tick_counts_but_does_not_raise(clean_db):
    async def factory():
        raise RuntimeError("provider construction blew up")

    sched = DiscoveryScanScheduler(lambda: clean_db, factory)
    await sched._tick()  # must not propagate
    assert sched._consecutive_failures == 1


async def test_scheduler_releases_the_handle_even_when_the_pass_fails(clean_db, monkeypatch):
    closed = False

    async def _close() -> None:
        nonlocal closed
        closed = True

    async def factory():
        return DiscoveryHandle(_FakeProvider(), None, _close)

    async def _boom(*a, **kw):
        raise RuntimeError("pass failed")

    monkeypatch.setattr("corp.workers.scheduler.discovery_scan.run_discovery_pass", _boom)
    sched = DiscoveryScanScheduler(lambda: clean_db, factory)
    await sched._tick()
    assert closed is True
    assert sched._consecutive_failures == 1


async def test_start_is_idempotent_and_stop_is_clean(clean_db):
    async def factory():
        return None

    sched = DiscoveryScanScheduler(lambda: clean_db, factory, interval_seconds=3600)
    sched.start()
    first = sched._task
    sched.start()
    assert sched._task is first, "start() twice must not spawn a second loop"
    await sched.stop()
    assert sched._task is None
    await sched.stop()  # stopping twice is a no-op


async def test_scheduler_gives_up_after_max_consecutive_failures(clean_db):
    async def factory():
        raise RuntimeError("always broken")

    sched = DiscoveryScanScheduler(lambda: clean_db, factory, interval_seconds=0)
    sched._consecutive_failures = sched.MAX_CONSECUTIVE_FAILURES - 1
    await sched._tick()
    assert sched._consecutive_failures == sched.MAX_CONSECUTIVE_FAILURES
    # _run_forever's guard means the loop exits rather than spinning.
    await asyncio.wait_for(sched._run_forever(), timeout=5)


async def test_giving_up_returns_immediately_without_a_backoff_sleep(clean_db):
    """Regression: the tick that first hits MAX_CONSECUTIVE_FAILURES used
    to fall through to the backoff sleep (up to interval_seconds * 32)
    before the loop's while-condition was re-checked, leaving the task
    alive -- and start() a no-op, since it only returns early while
    self._task is not None -- for a very long time after already having
    logged that it gave up. A large interval must not make _run_forever
    hang once the limit is hit on this tick."""
    async def factory():
        raise RuntimeError("always broken")

    sched = DiscoveryScanScheduler(lambda: clean_db, factory, interval_seconds=3600)
    sched._consecutive_failures = sched.MAX_CONSECUTIVE_FAILURES - 1
    await sched._tick()
    assert sched._consecutive_failures == sched.MAX_CONSECUTIVE_FAILURES
    await asyncio.wait_for(sched._run_forever(), timeout=1)


# ── Momentum source selection ────────────────────────────────────────


def _cfg(**overrides):
    from corp.config import Settings

    base = {"discovery_momentum_source": "youtube", "youtube_api_key": ""}
    base.update(overrides)
    return Settings(**base)


def test_youtube_is_the_default_momentum_source():
    from corp.config import Settings

    assert Settings.model_fields["discovery_momentum_source"].default == "youtube"


def test_youtube_without_a_key_ranks_by_rotation():
    from corp.workers.scheduler.discovery_scan import (
        build_momentum_provider,
        momentum_readiness,
    )

    cfg = _cfg(youtube_api_key="")
    assert build_momentum_provider(cfg, "US") is None
    source, ok, why = momentum_readiness(cfg)
    assert (source, ok) == ("youtube", False)
    assert "YOUTUBE_API_KEY" in why


def test_youtube_with_a_key_builds_the_official_trends_adapter(monkeypatch):
    from corp.workers.adapters import youtube_trends
    from corp.workers.scheduler.discovery_scan import (
        build_momentum_provider,
        momentum_readiness,
    )

    monkeypatch.setattr(youtube_trends, "build", lambda *a, **kw: object())
    cfg = _cfg(youtube_api_key="k", youtube_daily_quota_units=1234)
    provider = build_momentum_provider(cfg, "gb")
    assert isinstance(provider, youtube_trends.YouTubeTrendsAdapter)
    assert provider.region == "GB"
    assert provider._daily_quota == 1234, "must draw on the configured daily quota"
    assert momentum_readiness(cfg) == ("youtube", True, None)


def test_none_disables_momentum_entirely():
    from corp.workers.scheduler.discovery_scan import (
        build_momentum_provider,
        momentum_readiness,
    )

    cfg = _cfg(discovery_momentum_source="none", youtube_api_key="k")
    assert build_momentum_provider(cfg, "US") is None
    assert momentum_readiness(cfg)[1] is False


def test_googletrends_remains_selectable():
    from corp.workers.adapters.googletrends import GoogleTrendsAdapter
    from corp.workers.scheduler.discovery_scan import (
        build_momentum_provider,
        momentum_readiness,
    )

    cfg = _cfg(discovery_momentum_source="googletrends")
    assert isinstance(build_momentum_provider(cfg, "US"), GoogleTrendsAdapter)
    source, ok, why = momentum_readiness(cfg)
    assert source == "googletrends"
    # pytrends is not a dependency, so this is the honest answer by default.
    if not ok:
        assert "pytrends" in why


def test_an_unknown_momentum_source_is_rejected_at_startup():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _cfg(discovery_momentum_source="reddit")


# ── BROAD_TOPICS_PATH is honoured ────────────────────────────────────


async def test_the_pass_reads_the_configured_catalogue(clean_db, patched_pipeline, tmp_path):
    """BROAD_TOPICS_PATH used to be declared but never read: the scan always
    loaded rules/broad_topics.yaml whatever it was set to."""
    custom = tmp_path / "topics.yaml"
    custom.write_text(
        'version: "test"\nscan:\n  topics_per_pass: 5\n  geo: "US"\n'
        "topics:\n  - lock picking as a sport\n"
    )
    stats = await run_discovery_pass(
        clean_db, _FakeProvider(), broad_topics_path=str(custom)
    )
    assert [t for _, t in patched_pipeline["discover"]] == ["lock picking as a sport"]
    assert stats.scan["catalogue"] == 1
