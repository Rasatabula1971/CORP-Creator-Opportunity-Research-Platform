"""R15: the source-health circuit breaker, restored onto the LIVE discovery
engine.

The breaker shipped in 2026-09's "Slice 26" attached to
``MultiSourceDiscovery``, which T3's ``RecursiveNicheDiscovery`` superseded
three days later — so the spec's "monitored, and after continued no response
they are disconnected" behaviour silently stopped running. These tests cover
it where it now lives: inside the engine the API discover job and the R12
watch re-scanner actually use.

Adapter fan-out is faked throughout; no network.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from corp.config import settings
from corp.core.models.campaign import Campaign
from corp.core.models.workflow import RunStatus
from corp.workers.adapters.base import NormalizedContent, SourceAdapter
from corp.workers.adapters.health import (
    DEFAULT_DISCONNECT_AFTER,
    SourceHealthTracker,
    SourceStatus,
)
from corp.workers.intelligence.niche_discovery import (
    NICHE_FAN_OUT_PLATFORMS,
    RecursiveNicheDiscovery,
)
from corp.workers.providers.capabilities import SolutionProvider, TransactionProvider
from tests.integration.test_niche_discovery import (
    ScriptedProvider,
    _config,
    _content,
    _FakeAdapter,
    _niche,
)


async def _make_campaign(session: AsyncSession) -> Campaign:
    campaign = Campaign(name="Health Wiring Campaign")
    session.add(campaign)
    await session.flush()
    return campaign


class _DualCapabilityAdapter(_FakeAdapter, TransactionProvider, SolutionProvider):
    """Mirrors AppStore/Marketplace: two capabilities on one instance, so one
    platform yields two concurrent tasks under the fan-out's asyncio.gather."""

    def __init__(
        self,
        platform: str = "fakedual",
        items: list[NormalizedContent] | None = None,
        *,
        fail_transactions: bool = False,
        fail_solutions: bool = False,
    ) -> None:
        super().__init__(platform, items or [_content("dual-1", "evidence about it")])
        self.fail_transactions = fail_transactions
        self.fail_solutions = fail_solutions

    async def fetch_transactions(self, query: str) -> list[NormalizedContent]:
        if self.fail_transactions:
            raise RuntimeError("transactions boom")
        return await self.collect(query)

    async def fetch_solutions(self, query: str) -> list[NormalizedContent]:
        if self.fail_solutions:
            raise RuntimeError("solutions boom")
        return await self.collect(query)


def _provider() -> ScriptedProvider:
    return ScriptedProvider(
        {"broad topic": {"niches": [_niche("Niche A", ["topic a"], specific_enough=True)]}}
    )


@pytest.mark.asyncio
async def test_disconnected_source_is_skipped_and_never_built(
    clean_db: AsyncSession, monkeypatch, tmp_path
):
    """Design intent: a source past disconnect_after is not retried on every
    keyword — build_adapter must not even be called for it."""
    session = clean_db
    campaign = await _make_campaign(session)
    tracker = SourceHealthTracker(str(tmp_path))
    for _ in range(DEFAULT_DISCONNECT_AFTER):
        tracker.record_failure("stackexchange", RuntimeError("down"))
    assert tracker.get_status("stackexchange") == SourceStatus.DISCONNECTED

    built: list[str] = []

    def _build(platform: str) -> SourceAdapter:
        built.append(platform)
        return _DualCapabilityAdapter()

    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", _build
    )

    discovery = RecursiveNicheDiscovery(
        session, _provider(), rules_path="unused", config=_config(), health=tracker
    )
    await discovery.discover(campaign.id, "broad topic")

    assert "stackexchange" not in built
    assert built, "other platforms should still have been built"


@pytest.mark.asyncio
async def test_repeated_failures_trip_the_breaker(
    clean_db: AsyncSession, monkeypatch, tmp_path
):
    """The behaviour that went missing: consecutive failures accumulate until
    the source is disconnected, instead of being retried forever."""
    session = clean_db
    tracker = SourceHealthTracker(str(tmp_path))

    class _Broken(_DualCapabilityAdapter):
        pass

    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter",
        lambda platform: _Broken(fail_transactions=True, fail_solutions=True),
    )

    # Each discover() is one keyword pass over every platform.
    for _ in range(DEFAULT_DISCONNECT_AFTER):
        campaign = await _make_campaign(session)
        discovery = RecursiveNicheDiscovery(
            session, _provider(), rules_path="unused", config=_config(), health=tracker
        )
        await discovery.discover(campaign.id, "broad topic")

    assert tracker.get_status("stackexchange") == SourceStatus.DISCONNECTED
    assert tracker.is_available("stackexchange") is False


@pytest.mark.asyncio
async def test_partial_capability_failure_counts_as_one_success(
    clean_db: AsyncSession, monkeypatch, tmp_path
):
    """AppStore/Marketplace expose two capabilities. One failing while the
    other succeeds means the source IS responding — it must not be recorded
    as a failure, and the two results must not double-count."""
    session = clean_db
    campaign = await _make_campaign(session)
    tracker = SourceHealthTracker(str(tmp_path))
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter",
        lambda platform: _DualCapabilityAdapter(fail_transactions=True),
    )

    discovery = RecursiveNicheDiscovery(
        session, _provider(), rules_path="unused", config=_config(), health=tracker
    )
    await discovery.discover(campaign.id, "broad topic")

    rec = tracker.get_record("stackexchange")
    assert rec.status == SourceStatus.HEALTHY
    assert rec.consecutive_failures == 0
    assert rec.total_successes == 1, "one verdict per platform, not per capability"


@pytest.mark.asyncio
async def test_health_state_survives_a_new_engine_instance(
    clean_db: AsyncSession, monkeypatch, tmp_path
):
    """The lifetime bug this fix exists for: the engine is rebuilt per job and
    per watch re-scan, so failure counts must live outside it or a breaker
    could never trip."""
    session = clean_db
    tracker = SourceHealthTracker(str(tmp_path))
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter",
        lambda platform: _DualCapabilityAdapter(
            fail_transactions=True, fail_solutions=True
        ),
    )

    campaign = await _make_campaign(session)
    first = RecursiveNicheDiscovery(
        session, _provider(), rules_path="unused", config=_config(), health=tracker
    )
    await first.discover(campaign.id, "broad topic")
    after_first = tracker.get_record("stackexchange").consecutive_failures
    assert after_first == 1

    # A brand-new engine, as a later job or scheduler tick would build.
    campaign2 = await _make_campaign(session)
    second = RecursiveNicheDiscovery(
        session, _provider(), rules_path="unused", config=_config(), health=tracker
    )
    await second.discover(campaign2.id, "broad topic")
    assert tracker.get_record("stackexchange").consecutive_failures == 2


@pytest.mark.asyncio
async def test_every_source_disconnected_fails_the_run_loudly(
    clean_db: AsyncSession, monkeypatch, tmp_path
):
    """Stage 8 blocking finding: with every source circuit-broken, nothing is
    attempted, so stats would read 0/0 and the run would close 'completed'
    having done no work — a total outage would look identical to a quiet
    success. It must fail, and name why each source was passed over."""
    session = clean_db
    campaign = await _make_campaign(session)
    tracker = SourceHealthTracker(str(tmp_path))
    # Every platform in play here, so none is skipped as "disabled" instead.
    monkeypatch.setattr(settings, "discovery_disabled_sources", "")
    for platform in NICHE_FAN_OUT_PLATFORMS:
        for _ in range(DEFAULT_DISCONNECT_AFTER):
            tracker.record_failure(platform, RuntimeError("outage"))

    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter",
        lambda platform: pytest.fail("no adapter should be built"),
    )

    discovery = RecursiveNicheDiscovery(
        session, _provider(), rules_path="unused", config=_config(), health=tracker
    )
    run = await discovery.discover(campaign.id, "broad topic")

    assert run.status == RunStatus.FAILED.value
    assert "no niche source was available" in (run.error_message or "")
    # And the reason per source is recorded, not just a bare count.
    skipped = (run.stats or {}).get("extra", {}).get("skipped_sources", {})
    assert set(skipped) == set(NICHE_FAN_OUT_PLATFORMS)
    assert all(v == SourceStatus.DISCONNECTED for v in skipped.values())


@pytest.mark.asyncio
async def test_concurrent_saves_never_publish_corrupt_json(tmp_path):
    """Stage 8 blocking finding: save_async hands the write to a real thread,
    so two concurrent fan-outs in one process (a job and an R12 tick) raced on
    a per-process temp path and could publish interleaved bytes — which load()
    swallows, silently resetting every source to healthy."""
    import asyncio
    import json as json_mod

    trackers = [SourceHealthTracker(str(tmp_path)) for _ in range(8)]
    for i, tracker in enumerate(trackers):
        tracker.record_failure(f"platform{i}", RuntimeError("x"))

    await asyncio.gather(*(t.save_async() for t in trackers))

    state = tmp_path / "adapter_health.json"
    # Whichever writer won, the published file must be complete and valid.
    json_mod.loads(state.read_text(encoding="utf-8"))
    assert not list(tmp_path.glob("*.tmp")), "no temp file may survive"


def test_temp_file_is_cleaned_up_when_publish_fails(tmp_path, monkeypatch):
    """A failed os.replace must not orphan a temp file on every attempt."""
    tracker = SourceHealthTracker(str(tmp_path))
    tracker.record_failure("reddit", RuntimeError("nope"))
    monkeypatch.setattr(
        "corp.workers.adapters.health.os.replace",
        lambda *a, **k: (_ for _ in ()).throw(PermissionError("held open")),
    )

    tracker.save()  # swallowed, logged

    assert not (tmp_path / "adapter_health.json").exists()
    assert not list(tmp_path.glob("*.tmp")), "temp file must not be orphaned"


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    """A partial write would be read back as corrupt JSON and swallowed by
    load(), silently resetting every source to healthy — so the publish must
    be a rename."""
    tracker = SourceHealthTracker(str(tmp_path))
    tracker.record_failure("reddit", RuntimeError("nope"))
    tracker.save()

    state = tmp_path / "adapter_health.json"
    assert state.exists()
    assert not list(tmp_path.glob("*.tmp")), "temp file must be renamed, not left behind"

    reloaded = SourceHealthTracker(str(tmp_path))
    reloaded.load()
    assert reloaded.get_record("reddit").consecutive_failures == 1


@pytest.mark.asyncio
async def test_disabled_source_is_skipped_without_touching_health(
    clean_db: AsyncSession, monkeypatch, tmp_path
):
    """ADR-0066: a source switched off by configuration is a decision, not
    an outage. It must not be built, must not be recorded against source
    health (or it would trip the breaker for nothing), and the run must
    say why it was left out."""
    session = clean_db
    campaign = await _make_campaign(session)
    tracker = SourceHealthTracker(str(tmp_path))
    monkeypatch.setattr(settings, "discovery_disabled_sources", "stackexchange, Crowdfunding")

    built: list[str] = []

    def _build(platform: str) -> SourceAdapter:
        built.append(platform)
        return _DualCapabilityAdapter()

    monkeypatch.setattr("corp.workers.intelligence.niche_discovery.build_adapter", _build)

    discovery = RecursiveNicheDiscovery(
        session, _provider(), rules_path="unused", config=_config(), health=tracker
    )
    run = await discovery.discover(campaign.id, "broad topic")

    assert "stackexchange" not in built and "crowdfunding" not in built
    assert built, "the other platforms are still built"
    assert tracker.get_record("stackexchange").total_failures == 0
    assert tracker.get_record("crowdfunding").total_failures == 0
    skipped = (run.stats or {}).get("extra", {}).get("skipped_sources", {})
    assert skipped["stackexchange"] == "disabled by DISCOVERY_DISABLED_SOURCES"
    assert skipped["crowdfunding"] == "disabled by DISCOVERY_DISABLED_SOURCES"
    assert run.status != RunStatus.FAILED.value


@pytest.mark.asyncio
async def test_unconfigured_adapter_is_skipped_without_a_health_failure(
    clean_db: AsyncSession, monkeypatch, tmp_path
):
    """A registry AdapterConfigError (e.g. every marketplace site removed as
    blocked) is configuration, not an outage: skipped with a reason, no
    breaker accounting."""
    from corp.workers.adapters.registry import AdapterConfigError

    session = clean_db
    campaign = await _make_campaign(session)
    tracker = SourceHealthTracker(str(tmp_path))
    monkeypatch.setattr(settings, "discovery_disabled_sources", "")

    def _build(platform: str) -> SourceAdapter:
        if platform == "marketplace":
            raise AdapterConfigError("no usable marketplace")
        return _DualCapabilityAdapter()

    monkeypatch.setattr("corp.workers.intelligence.niche_discovery.build_adapter", _build)

    discovery = RecursiveNicheDiscovery(
        session, _provider(), rules_path="unused", config=_config(), health=tracker
    )
    run = await discovery.discover(campaign.id, "broad topic")

    assert tracker.get_record("marketplace").total_failures == 0
    skipped = (run.stats or {}).get("extra", {}).get("skipped_sources", {})
    assert skipped["marketplace"] == "not configured; details in the server log"
