"""No-DB unit tests for the orchestrator's stage-crash handling.

When a stage *raises* (as opposed to returning a run with status "failed"),
the crashing pipeline has marked its run failed and flushed it, but not
committed. The orchestrator must commit so that failed run survives as
research memory (ADR-0009), then re-raise the original crash. A poisoned
session (commit impossible) must be rolled back so the caller gets a usable
session, and the original crash must still propagate.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corp.workers.orchestrator import ResearchOrchestrator


class _FakeCreator:
    def __init__(self) -> None:
        self.status = MagicMock(value="clustered")


def _fake_session() -> MagicMock:
    session = MagicMock()
    session.get = AsyncMock(return_value=_FakeCreator())
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _orchestrator(session: MagicMock) -> ResearchOrchestrator:
    return ResearchOrchestrator(
        session,
        provider=MagicMock(),
        embedder_factory=MagicMock(),
    )


@patch("corp.workers.orchestrator.IntelligencePipeline")
async def test_stage_crash_commits_failed_run_then_reraises(mock_intel):
    mock_intel.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
    session = _fake_session()
    orch = _orchestrator(session)

    with pytest.raises(RuntimeError, match="boom"):
        await orch.run("creator-1", skip_collect=True)

    # The failed run row is persisted, not rolled away.
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@patch("corp.workers.orchestrator.IntelligencePipeline")
async def test_poisoned_session_rolls_back_and_reraises_original(mock_intel):
    mock_intel.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
    session = _fake_session()
    # Simulate a transaction poisoned by a DB error: commit is impossible.
    session.commit = AsyncMock(side_effect=RuntimeError("transaction is aborted"))
    orch = _orchestrator(session)

    with pytest.raises(RuntimeError, match="boom"):
        await orch.run("creator-1", skip_collect=True)

    # Commit was attempted, failed, and we rolled back to a usable session.
    session.commit.assert_awaited_once()
    session.rollback.assert_awaited_once()


async def test_missing_creator_raises_without_touching_commit():
    session = _fake_session()
    session.get = AsyncMock(return_value=None)
    orch = _orchestrator(session)

    with pytest.raises(ValueError, match="Creator not found"):
        await orch.run("nope", skip_collect=True)

    # No run was started, so there is nothing to persist or roll back.
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
