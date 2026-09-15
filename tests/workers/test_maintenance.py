"""No-DB unit tests for the prune maintenance service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from corp.workers.maintenance import PruneService


def _session(count: int) -> MagicMock:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=count)
    session.execute = AsyncMock()
    return session


async def test_dry_run_counts_but_does_not_delete():
    session = _session(42)
    report = await PruneService(session, retention_days=90).prune(apply=False)

    assert report.metrics_snapshots == 42
    assert report.applied is False
    assert report.retention_days == 90
    session.execute.assert_not_awaited()  # nothing deleted on a dry run


async def test_apply_deletes_when_rows_match():
    session = _session(42)
    report = await PruneService(session, retention_days=30).prune(apply=True)

    assert report.metrics_snapshots == 42
    assert report.applied is True
    session.execute.assert_awaited_once()  # the DELETE was issued


async def test_apply_skips_delete_when_nothing_to_prune():
    session = _session(0)
    report = await PruneService(session).prune(apply=True)

    assert report.metrics_snapshots == 0
    session.execute.assert_not_awaited()  # no rows → no DELETE


async def test_none_count_treated_as_zero():
    session = _session(None)
    report = await PruneService(session).prune(apply=True)

    assert report.metrics_snapshots == 0
    session.execute.assert_not_awaited()


def test_negative_retention_rejected():
    with pytest.raises(ValueError):
        PruneService(MagicMock(), retention_days=-1)


async def test_report_serializes():
    session = _session(3)
    report = await PruneService(session, retention_days=7).prune(apply=False)
    d = report.to_dict()
    assert d["metrics_snapshots"] == 3
    assert d["retention_days"] == 7
    assert d["applied"] is False
    assert "cutoff" in d
