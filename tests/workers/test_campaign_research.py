"""No-DB unit tests for the campaign research batch's per-creator resilience.

When a creator's research crashes on a DB error, the orchestrator rolls the
shared session back. A rollback expires every loaded ORM instance (the
``expire_on_commit=False`` flag only covers commit), and an ``AsyncSession``
cannot lazy-load an expired attribute — it raises ``MissingGreenlet``. The
batch must therefore never touch a ``Creator`` instance after the researcher
ran, and must keep its own run row usable so the batch still closes.
"""

from typing import TypeVar, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import CreatorStatus
from corp.workers.campaign_research import (
    BatchConfig,
    CampaignResearchBatch,
    CreatorResearcher,
)

T = TypeVar("T")


class _ExpiredAttributeError(RuntimeError):
    """Stands in for sqlalchemy.exc.MissingGreenlet on an expired instance."""


class _FakeCreator:
    """A Creator whose attributes blow up once the session has rolled back."""

    def __init__(self, id: str, status: CreatorStatus = CreatorStatus.DISCOVERED) -> None:
        self._id = id
        self._status = status
        self.expired = False

    def _get(self, value: T) -> T:
        if self.expired:
            raise _ExpiredAttributeError("expired attribute load outside greenlet")
        return value

    @property
    def id(self) -> str:
        return self._get(self._id)

    @property
    def name(self) -> str:
        return self._get(f"name-{self._id}")

    @property
    def status(self) -> CreatorStatus:
        return self._get(self._status)


class _FakeSession:
    def __init__(self) -> None:
        self.contents: set[int] = set()
        self.refreshed: list[object] = []
        self.added: list[object] = []
        self.flush = AsyncMock()

    def __contains__(self, obj: object) -> bool:
        return id(obj) in self.contents

    async def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)

    def add(self, obj: object) -> None:
        self.added.append(obj)
        self.contents.add(id(obj))


class _Researcher:
    """Crashes on ``crash_id`` and, like the orchestrator's rollback, expires
    every creator the batch loaded; succeeds for everyone else."""

    def __init__(self, creators: list[_FakeCreator], crash_id: str) -> None:
        self._creators = creators
        self._crash_id = crash_id
        self.calls: list[str] = []

    async def run(self, creator_id: str, *, skip_collect: bool = False) -> MagicMock:
        self.calls.append(creator_id)
        if creator_id == self._crash_id:
            for c in self._creators:
                c.expired = True
            raise RuntimeError("transaction is aborted")
        return MagicMock(final_status=CreatorStatus.HUMAN_REVIEW.value)


def _run() -> MagicMock:
    run = MagicMock()
    run.id = "run-1"
    run.status = "running"
    return run


def _batch(
    researcher: CreatorResearcher,
    session: _FakeSession,
    creators: list[_FakeCreator] | None = None,
    config: BatchConfig | None = None,
) -> CampaignResearchBatch:
    batch = CampaignResearchBatch(researcher, cast(AsyncSession, session), config)
    if creators is not None:
        batch._eligible_creators = AsyncMock(return_value=creators)  # type: ignore[method-assign]
    return batch


@patch("corp.workers.campaign_research.fail_run", new_callable=AsyncMock)
@patch("corp.workers.campaign_research.finish_run", new_callable=AsyncMock)
@patch("corp.workers.campaign_research.start_run", new_callable=AsyncMock)
async def test_creator_crash_with_rollback_does_not_sink_batch(
    mock_start: AsyncMock, mock_finish: AsyncMock, mock_fail: AsyncMock,
) -> None:
    run = _run()
    mock_start.return_value = run
    mock_finish.side_effect = lambda session, r, stats: r

    creators = [_FakeCreator("a"), _FakeCreator("b"), _FakeCreator("c")]
    researcher = _Researcher(creators, crash_id="b")
    batch = _batch(researcher, _FakeSession(), creators)

    result = await batch.run_campaign("camp-1")

    assert result is run
    # Every creator was attempted; the crash did not stop the loop.
    assert researcher.calls == ["a", "b", "c"]
    stats = mock_finish.call_args[0][2]
    assert stats.succeeded == 2
    assert stats.failed == 1
    outcomes = {r["creator_id"]: r["outcome"] for r in stats.extra["results"]}
    assert outcomes == {"a": "succeeded", "b": "errored", "c": "succeeded"}
    # Names were captured before the rollback, not read from expired instances.
    assert {r["name"] for r in stats.extra["results"]} == {"name-a", "name-b", "name-c"}
    mock_fail.assert_not_awaited()


@patch("corp.workers.campaign_research.fail_run", new_callable=AsyncMock)
@patch("corp.workers.campaign_research.finish_run", new_callable=AsyncMock)
@patch("corp.workers.campaign_research.start_run", new_callable=AsyncMock)
async def test_run_row_is_reattached_after_creator_crash(
    mock_start: AsyncMock, mock_finish: AsyncMock, mock_fail: AsyncMock,
) -> None:
    run = _run()
    mock_start.return_value = run
    mock_finish.side_effect = lambda session, r, stats: r

    # The run row was still pending when the rollback expunged it: re-add.
    creators = [_FakeCreator("a")]
    session = _FakeSession()
    await _batch(_Researcher(creators, crash_id="a"), session, creators).run_campaign("camp-1")
    assert session.added == [run]
    assert session.refreshed == []

    # The run row had been committed by an earlier orchestrator step: refresh.
    creators = [_FakeCreator("a")]
    session = _FakeSession()
    session.contents.add(id(run))
    await _batch(_Researcher(creators, crash_id="a"), session, creators).run_campaign("camp-1")
    assert session.refreshed == [run]
    assert session.added == []


@patch("corp.workers.campaign_research.fail_run", new_callable=AsyncMock)
@patch("corp.workers.campaign_research.finish_run", new_callable=AsyncMock)
@patch("corp.workers.campaign_research.start_run", new_callable=AsyncMock)
async def test_skip_uses_snapshot_status(
    mock_start: AsyncMock, mock_finish: AsyncMock, mock_fail: AsyncMock,
) -> None:
    run = _run()
    mock_start.return_value = run
    mock_finish.side_effect = lambda session, r, stats: r
    creators = [_FakeCreator("a", CreatorStatus.HUMAN_REVIEW), _FakeCreator("b")]
    researcher = _Researcher(creators, crash_id="none")
    batch = _batch(researcher, _FakeSession(), creators, BatchConfig(limit=2))

    await batch.run_campaign("camp-1")

    assert researcher.calls == ["b"]
    stats = mock_finish.call_args[0][2]
    assert stats.skipped == 1
    skipped = next(r for r in stats.extra["results"] if r["outcome"] == "skipped")
    assert skipped["creator_id"] == "a"
    assert "status=human_review" in skipped["reason"]


@patch("corp.workers.campaign_research.fail_run", new_callable=AsyncMock)
@patch("corp.workers.campaign_research.finish_run", new_callable=AsyncMock)
@patch("corp.workers.campaign_research.start_run", new_callable=AsyncMock)
async def test_batch_failure_with_expired_run_keeps_original_error(
    mock_start: AsyncMock, mock_finish: AsyncMock, mock_fail: AsyncMock,
) -> None:
    """Reading ``run.status`` on an expired row must not mask the batch's crash."""
    run = MagicMock()
    type(run).status = property(lambda self: (_ for _ in ()).throw(_ExpiredAttributeError("x")))
    mock_start.return_value = run
    batch = _batch(_Researcher([], crash_id="none"), _FakeSession())
    batch._eligible_creators = AsyncMock(side_effect=ValueError("query failed"))  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="query failed"):
        await batch.run_campaign("camp-1")
    mock_fail.assert_not_awaited()
