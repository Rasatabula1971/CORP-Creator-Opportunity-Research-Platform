"""Unit tests for session-aware creator transitions — no database."""

import pytest

from corp.core.models.creator import Creator, CreatorStatus
from corp.core.state.machine import InvalidTransitionError
from corp.core.state.transitions import advance, restore


class FakeSession:
    async def flush(self) -> None:
        pass


def _creator(status: CreatorStatus) -> Creator:
    return Creator(name="t", status=status)


async def test_advance_valid_transition():
    c = _creator(CreatorStatus.DISCOVERED)
    assert await advance(FakeSession(), c, CreatorStatus.COLLECTING) is True
    assert c.status == CreatorStatus.COLLECTING


async def test_advance_same_status_is_noop():
    c = _creator(CreatorStatus.SCORED)
    assert await advance(FakeSession(), c, CreatorStatus.SCORED) is False


async def test_advance_invalid_is_skipped_by_default():
    c = _creator(CreatorStatus.SCORED)
    assert await advance(FakeSession(), c, CreatorStatus.COLLECTING) is False
    assert c.status == CreatorStatus.SCORED


async def test_advance_invalid_raises_when_strict():
    c = _creator(CreatorStatus.SCORED)
    with pytest.raises(InvalidTransitionError):
        await advance(FakeSession(), c, CreatorStatus.COLLECTING, strict=True)


async def test_watching_can_recollect():
    c = _creator(CreatorStatus.WATCHING)
    assert await advance(FakeSession(), c, CreatorStatus.COLLECTING) is True


async def test_restore_bypasses_validation():
    c = _creator(CreatorStatus.EXTRACTING)
    await restore(FakeSession(), c, CreatorStatus.COLLECTED)
    assert c.status == CreatorStatus.COLLECTED
