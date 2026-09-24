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

from corp.core.models.workflow import ResearchRun
from corp.workers.orchestrator import ResearchOrchestrator


class _FakeCreator:
    def __init__(self) -> None:
        self.id = "creator-1"
        self.status = MagicMock(value="clustered")


def _fake_session() -> MagicMock:
    session = MagicMock()
    session.get = AsyncMock(return_value=_FakeCreator())
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
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


@patch("corp.workers.orchestrator.DossierGenerator")
@patch("corp.workers.orchestrator.ScoringPipeline")
@patch("corp.workers.orchestrator.IntentPipeline")
@patch("corp.workers.orchestrator.ClusterPipeline")
@patch("corp.workers.orchestrator.IntelligencePipeline")
async def test_dossier_crash_creates_and_fails_its_own_run(
    mock_intel, mock_cluster, mock_intent, mock_scoring, mock_dossier
):
    """Every other stage records its own ResearchRun on crash (asserted
    above); dossier generation used to have no run at all, so a crash there
    left no record it was even attempted. It must now behave the same way."""
    ok_run = MagicMock(status="completed")
    mock_intel.return_value.run = AsyncMock(return_value=ok_run)
    mock_cluster.return_value.run = AsyncMock(return_value=ok_run)
    mock_intent.return_value.run = AsyncMock(return_value=ok_run)
    mock_scoring.return_value.run = AsyncMock(return_value=ok_run)
    mock_dossier.return_value.generate = AsyncMock(side_effect=RuntimeError("dossier boom"))

    session = _fake_session()
    orch = _orchestrator(session)

    with pytest.raises(RuntimeError, match="dossier boom"):
        await orch.run("creator-1", skip_collect=True)

    dossier_runs = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], ResearchRun)
        and call.args[0].config_snapshot.get("pipeline") == "dossier"
    ]
    assert len(dossier_runs) == 1
    assert dossier_runs[0].status == "failed"
    assert dossier_runs[0].error_message == "RuntimeError; details in the server log"

    # Still research memory: the crash-persist commit went through, not rolled back.
    assert session.commit.await_count >= 1
    session.rollback.assert_not_awaited()


async def test_missing_creator_raises_without_touching_commit():
    session = _fake_session()
    session.get = AsyncMock(return_value=None)
    orch = _orchestrator(session)

    with pytest.raises(ValueError, match="Creator not found"):
        await orch.run("nope", skip_collect=True)

    # No run was started, so there is nothing to persist or roll back.
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
