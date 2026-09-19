"""Tests for the app lifespan: scheduler starts on boot, stops on shutdown."""

from unittest.mock import AsyncMock, MagicMock, patch

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
            cls.assert_called_once_with(
                mock_session,
                "rules/scoring.yaml",
            )


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
