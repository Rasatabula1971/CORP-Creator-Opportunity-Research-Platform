"""Tests for the app lifespan: scheduler starts on boot, stops on shutdown."""

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from corp.api.app import lifespan


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_scheduler():
    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    mock_scheduler.stop = AsyncMock()

    with patch(
        "corp.api.app.RegistryRescanScheduler", return_value=mock_scheduler
    ) as cls:
        app = FastAPI()
        async with lifespan(app):
            cls.assert_called_once()
            mock_scheduler.start.assert_called_once()
            mock_scheduler.stop.assert_not_called()

        mock_scheduler.stop.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_passes_correct_config():
    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    mock_scheduler.stop = AsyncMock()

    with patch(
        "corp.api.app.RegistryRescanScheduler", return_value=mock_scheduler
    ) as cls, patch("corp.api.app.settings") as mock_settings, patch(
        "corp.api.app.async_session"
    ) as mock_session:
        mock_settings.scoring_rules_path = "rules/scoring.yaml"

        app = FastAPI()
        async with lifespan(app):
            # R12c: the scheduler is handed the re-research factory and the
            # campaign-busy check alongside the original two arguments.
            cls.assert_called_once_with(
                mock_session,
                "rules/scoring.yaml",
                rescanner_factory=ANY,
                is_busy=ANY,
            )


# ---------- R12c: the scheduler's provider lives across ticks ----------


class _FakePool:
    def __init__(self, cooling: bool) -> None:
        self.cooling, self.closed = cooling, 0

    def available(self) -> list[object]:
        return [] if self.cooling else [object()]

    async def close(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_rescan_providers_reuse_one_provider_and_defer_when_cooling():
    from corp.api.app import RescanProviders
    from corp.workers.scheduler.registry_rescan import RescanDeferredError
    from corp.workers.watch_rescan import WatchRescanConfig

    pool = _FakePool(cooling=False)
    providers = RescanProviders()
    session = MagicMock()
    with patch("corp.workers.providers.factory.build_provider", return_value=pool) as build, patch(
        "corp.api.jobs._embedder_factory", return_value=lambda: None
    ), patch("corp.workers.watch_rescan.build_watch_rescanner") as build_rescanner:
        first = await providers.factory(session, WatchRescanConfig())
        second = await providers.factory(session, WatchRescanConfig())
        assert first is not None and second is not None
        build.assert_called_once()  # one provider for the scheduler's lifetime
        assert build_rescanner.call_args.kwargs["config"] == WatchRescanConfig()
        await first.aclose()
        assert pool.closed == 0  # the tick's handle does not close the shared provider

        pool.cooling = True
        with pytest.raises(RescanDeferredError):
            await providers.factory(session, WatchRescanConfig())
        # The config flag can turn the deferral off.
        assert (
            await providers.factory(session, WatchRescanConfig(skip_when_provider_cooling=False))
            is not None
        )

    await providers.aclose()
    assert pool.closed == 1


@pytest.mark.asyncio
async def test_rescan_providers_close_provider_when_rescanner_build_fails():
    from corp.api.app import RescanProviders
    from corp.workers.watch_rescan import WatchRescanConfig

    pool = _FakePool(cooling=False)
    providers = RescanProviders()
    with patch("corp.workers.providers.factory.build_provider", return_value=pool), patch(
        "corp.api.jobs._embedder_factory", return_value=lambda: None
    ), patch(
        "corp.workers.watch_rescan.build_watch_rescanner", side_effect=FileNotFoundError("rules")
    ):
        with pytest.raises(FileNotFoundError):
            await providers.factory(MagicMock(), WatchRescanConfig())
    assert pool.closed == 1


@pytest.mark.asyncio
async def test_rescan_providers_return_none_when_unconfigured():
    from corp.api.app import RescanProviders
    from corp.workers.providers.factory import ProviderConfigError
    from corp.workers.watch_rescan import WatchRescanConfig

    providers = RescanProviders()
    with patch(
        "corp.workers.providers.factory.build_provider", side_effect=ProviderConfigError("none")
    ) as build:
        assert await providers.factory(MagicMock(), WatchRescanConfig()) is None
        assert await providers.factory(MagicMock(), WatchRescanConfig()) is None
        build.assert_called_once()  # warned once, not every tick


@pytest.mark.asyncio
async def test_lifespan_stops_scheduler_on_exception():
    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    mock_scheduler.stop = AsyncMock()

    with patch(
        "corp.api.app.RegistryRescanScheduler", return_value=mock_scheduler
    ):
        app = FastAPI()
        with pytest.raises(RuntimeError, match="boom"):
            async with lifespan(app):
                raise RuntimeError("boom")

        mock_scheduler.stop.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_degrades_gracefully_when_scheduler_init_fails():
    with patch(
        "corp.api.app.RegistryRescanScheduler",
        side_effect=FileNotFoundError("rules file missing"),
    ):
        app = FastAPI()
        async with lifespan(app):
            pass


# ---------- Audit fix: _discovery_busy sees a campaign-less discovery job ----------


def test_discovery_busy_true_for_a_campaign_less_discovery_job(monkeypatch):
    """Two near-simultaneous autonomous passes (the scheduler's own tick and
    a manual POST /discovery/run with no campaign_id) can each find the
    standing autonomous campaign missing and create it twice. The scheduler
    must stand down for the other one, even though neither job carries a
    campaign_id."""
    from corp.api.app import _discovery_busy
    from corp.api.jobs import JobRegistry

    fresh = JobRegistry()
    fresh.create("discovery")  # no campaign_id, exactly like an autonomous pass
    monkeypatch.setattr("corp.api.jobs.registry", fresh)

    assert _discovery_busy() is True


def test_discovery_busy_false_when_only_unrelated_jobs_are_active(monkeypatch):
    from corp.api.app import _discovery_busy
    from corp.api.jobs import JobRegistry

    fresh = JobRegistry()
    fresh.create("research", creator_id="creator-1")
    monkeypatch.setattr("corp.api.jobs.registry", fresh)

    assert _discovery_busy() is False


def test_discovery_busy_still_true_for_a_campaign_bound_job(monkeypatch):
    from corp.api.app import _discovery_busy
    from corp.api.jobs import JobRegistry

    fresh = JobRegistry()
    fresh.create("research", campaign_id="c1")
    monkeypatch.setattr("corp.api.jobs.registry", fresh)

    assert _discovery_busy() is True
