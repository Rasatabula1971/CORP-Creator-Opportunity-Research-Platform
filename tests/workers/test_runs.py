"""Unit tests for the shared run lifecycle helpers — no database."""

import pytest

from corp.core.models.workflow import ResearchRun, RunStatus
from corp.workers.intelligence.runs import (
    PipelineFailureError,
    PipelineStats,
    finish_run,
    resolve_status,
)


class FakeSession:
    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


def test_stats_counts_and_rate():
    s = PipelineStats()
    s.ok()
    s.ok()
    s.fail(RuntimeError("boom"))
    s.skip()
    assert (s.attempted, s.succeeded, s.failed, s.skipped) == (3, 2, 1, 1)
    assert s.failure_rate == pytest.approx(1 / 3)
    assert s.last_error == "boom"
    d = s.to_dict()
    assert d["failure_rate"] == pytest.approx(0.3333, abs=1e-4)


def test_stats_zero_attempts_has_zero_rate():
    assert PipelineStats().failure_rate == 0.0


@pytest.mark.parametrize(
    "ok, failed, expected",
    [
        (0, 0, RunStatus.COMPLETED),
        (10, 0, RunStatus.COMPLETED),
        (9, 1, RunStatus.COMPLETED),  # 10% <= 20%
        (7, 3, RunStatus.PARTIAL),  # 30% > 20%
        (0, 5, RunStatus.FAILED),  # everything failed
    ],
)
def test_resolve_status(ok, failed, expected):
    s = PipelineStats()
    for _ in range(ok):
        s.ok()
    for _ in range(failed):
        s.fail(RuntimeError("x"))
    assert resolve_status(s, 0.2) == expected.value


async def test_finish_run_completed():
    run = ResearchRun(creator_id="c1", status="running")
    stats = PipelineStats()
    stats.ok()
    session = FakeSession()
    await finish_run(session, run, stats)
    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.stats["succeeded"] == 1
    assert run.error_message is None
    assert session.flushes == 1


async def test_finish_run_partial_records_reason():
    run = ResearchRun(creator_id="c1", status="running")
    stats = PipelineStats()
    for _ in range(6):
        stats.ok()
    for _ in range(4):
        stats.fail(RuntimeError("provider timeout"))
    await finish_run(FakeSession(), run, stats, max_failure_rate=0.2)
    assert run.status == "partial"
    assert "4/10" in run.error_message
    assert "provider timeout" in run.error_message


async def test_finish_run_all_failed_raises_with_last_error():
    run = ResearchRun(creator_id="c1", status="running")
    stats = PipelineStats()
    stats.fail(RuntimeError("LLM down"))
    stats.fail(RuntimeError("LLM down"))
    with pytest.raises(PipelineFailureError, match="LLM down"):
        await finish_run(FakeSession(), run, stats)
    assert run.status == "failed"
    assert isinstance(PipelineFailureError("x"), RuntimeError)
