"""Unit tests for the shared run lifecycle helpers — no database."""

import pytest

from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.workflow import ResearchRun, RunStatus
from corp.workers.intelligence.runs import (
    PipelineStats,
    finish_run,
    resolve_status,
    stage,
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
    # Never the exception's own text (it can carry DSNs, keyed URLs, paths)
    assert s.last_error == "RuntimeError; details in the server log"
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
    assert "RuntimeError" in run.error_message
    assert "provider timeout" not in run.error_message


async def test_finish_run_all_failed_returns_failed_run_without_raising():
    """A fully failed run is still research memory: it must come back to the
    caller (who commits it), not be lost behind an exception and a rollback.
    Seen live twice before this changed (Reddit 403 in Slice 7; a Groq stall)."""
    run = ResearchRun(creator_id="c1", status="running")
    stats = PipelineStats()
    stats.fail(RuntimeError("LLM down"))
    stats.fail(RuntimeError("LLM down"))
    session = FakeSession()
    returned = await finish_run(session, run, stats)
    assert returned is run
    assert run.status == "failed"
    assert "RuntimeError" in run.error_message
    assert "LLM down" not in run.error_message
    assert run.completed_at is not None
    assert session.flushes == 1


# ── stage(): a failed run must not advance the creator ───────────────


class FakeSessionWithCreator(FakeSession):
    def __init__(self, creator: Creator) -> None:
        super().__init__()
        self._creator = creator

    async def get(self, model, key):
        return self._creator


async def test_stage_failed_run_restores_previous_status():
    creator = Creator(id="c1", name="c", status=CreatorStatus.COLLECTED)
    run = ResearchRun(creator_id="c1", status="running")
    async with stage(
        FakeSessionWithCreator(creator),
        "c1",
        working=CreatorStatus.EXTRACTING,
        done=CreatorStatus.EXTRACTED,
        run=run,
    ) as c:
        assert c.status == CreatorStatus.EXTRACTING
        run.status = "failed"  # what finish_run does when every unit fails
    assert creator.status == CreatorStatus.COLLECTED


async def test_stage_completed_run_advances():
    creator = Creator(id="c1", name="c", status=CreatorStatus.COLLECTED)
    run = ResearchRun(creator_id="c1", status="running")
    async with stage(
        FakeSessionWithCreator(creator),
        "c1",
        working=CreatorStatus.EXTRACTING,
        done=CreatorStatus.EXTRACTED,
        run=run,
    ):
        run.status = "partial"  # partial still produced something: advance
    assert creator.status == CreatorStatus.EXTRACTED


async def test_stage_without_run_keeps_old_behaviour():
    creator = Creator(id="c1", name="c", status=CreatorStatus.COLLECTED)
    async with stage(
        FakeSessionWithCreator(creator),
        "c1",
        working=CreatorStatus.EXTRACTING,
        done=CreatorStatus.EXTRACTED,
    ):
        pass
    assert creator.status == CreatorStatus.EXTRACTED


async def test_stage_exception_still_restores():
    creator = Creator(id="c1", name="c", status=CreatorStatus.COLLECTED)
    with pytest.raises(RuntimeError, match="boom"):
        async with stage(
            FakeSessionWithCreator(creator),
            "c1",
            working=CreatorStatus.EXTRACTING,
            done=CreatorStatus.EXTRACTED,
        ):
            raise RuntimeError("boom")
    assert creator.status == CreatorStatus.COLLECTED
