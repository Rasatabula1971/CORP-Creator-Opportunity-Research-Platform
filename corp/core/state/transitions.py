"""Session-aware creator status transitions used by the pipelines.

Pipelines call :func:`advance` on entry and exit. Transitions are validated
against the state machine; an invalid one is logged and skipped unless
``strict=True``. This keeps re-runs on an already-scored creator from crashing
while still preventing nonsense like SCORED -> COLLECTED when strict.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator, CreatorStatus
from corp.core.state.machine import InvalidTransitionError, validate_transition

logger = logging.getLogger(__name__)


async def advance(
    session: AsyncSession,
    creator: Creator,
    target: CreatorStatus,
    *,
    strict: bool = False,
) -> bool:
    """Move ``creator`` to ``target`` if the state machine allows it.

    Returns True when the status changed. With ``strict=False`` an invalid
    transition returns False; with ``strict=True`` it raises.
    """
    if creator.status == target:
        return False
    try:
        validate_transition(creator.status, target)
    except InvalidTransitionError:
        if strict:
            raise
        logger.info(
            "Skipping status change %s -> %s for creator %s (not allowed)",
            creator.status.value,
            target.value,
            creator.id,
        )
        return False

    creator.status = target
    await session.flush()
    return True


async def restore(session: AsyncSession, creator: Creator, previous: CreatorStatus) -> None:
    """Put a creator back to ``previous`` after a failed stage, bypassing validation."""
    if creator.status != previous:
        logger = logging.getLogger(__name__)
        logger.warning(
            "restore: %s status %s -> %s (bypassing state machine)",
            creator.id,
            creator.status.value,
            previous.value,
        )
        creator.status = previous
        await session.flush()
