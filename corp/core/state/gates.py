"""Gate A logic — human review decisions with state machine transitions —
and the dossier-gate mirror that keeps Creator.status consistent with the
creator's active dossiers (R12b)."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.scoring import OpportunityScore
from corp.core.models.workflow import DecisionType, Gate, HumanDecision
from corp.core.state.machine import InvalidTransitionError, validate_transition

logger = logging.getLogger(__name__)

_DECISION_TO_STATUS = {
    DecisionType.APPROVE: CreatorStatus.APPROVED,
    DecisionType.REJECT: CreatorStatus.REJECTED,
    DecisionType.WATCH: CreatorStatus.WATCHING,
}


async def record_gate_a_decision(
    session: AsyncSession,
    creator: Creator,
    decision: DecisionType,
    rationale: str | None = None,
    decided_by: str | None = None,
    opportunity_score_id: str | None = None,
) -> HumanDecision:
    """Record a Gate A decision and transition the creator's status.

    Raises InvalidTransitionError if the creator is not in HUMAN_REVIEW state.
    """
    target_status = _DECISION_TO_STATUS.get(decision)
    if target_status is None:
        valid = ", ".join(d.value for d in _DECISION_TO_STATUS)
        raise ValueError(
            f"Decision {decision.value!r} is not valid for Gate A "
            f"(expected one of {valid})"
        )
    validate_transition(creator.status, target_status)

    if opportunity_score_id is not None:
        score = await session.get(OpportunityScore, opportunity_score_id)
        if score is None or score.creator_id != creator.id:
            raise ValueError("opportunity_score_id does not belong to this creator")

    record = HumanDecision(
        creator_id=creator.id,
        opportunity_score_id=opportunity_score_id,
        decision=decision,
        gate=Gate.GATE_A,
        rationale=rationale,
        decided_by=decided_by,
    )
    session.add(record)

    creator.status = target_status
    await session.flush()

    return record


def creator_status_for_dossiers(statuses: list[DossierStatus]) -> CreatorStatus | None:
    """The creator status implied by its ACTIVE dossiers, by precedence:
    any approved → APPROVED (the partnership path wins); anything still
    awaiting a human (pending review, research more in progress) →
    HUMAN_REVIEW; otherwise any watched → WATCHING; all rejected →
    REJECTED. None when there are no active dossiers."""
    if not statuses:
        return None
    if DossierStatus.APPROVED in statuses:
        return CreatorStatus.APPROVED
    if any(
        s in (DossierStatus.PENDING_REVIEW, DossierStatus.RESEARCH_MORE_IN_PROGRESS)
        for s in statuses
    ):
        return CreatorStatus.HUMAN_REVIEW
    if DossierStatus.WATCHING in statuses:
        return CreatorStatus.WATCHING
    return CreatorStatus.REJECTED


async def mirror_creator_status(session: AsyncSession, creator_id: str) -> CreatorStatus | None:
    """Move Creator.status to match the creator's active dossiers after a
    dossier-gate decision (R12b). Dossier.status is the documented mirror of
    the latest HumanDecision; before this the dossier gate left the creator
    at HUMAN_REVIEW even when every dossier was watched, approved or
    rejected — which also made a watched creator un-researchable, since the
    orchestrator may only restart from WATCHING.

    Only legal state-machine moves are made. A creator whose status is not
    gate-adjacent (e.g. a fixture at DISCOVERED, or one mid-pipeline) is left
    alone with a warning rather than failing the decision. Returns the new
    status, or None when nothing changed."""
    creator = await session.get(Creator, creator_id)
    if creator is None:
        return None
    statuses = list(
        (
            await session.execute(
                select(Dossier.status).where(
                    Dossier.creator_id == creator_id, Dossier.superseded_at.is_(None)
                )
            )
        ).scalars().all()
    )
    target = creator_status_for_dossiers(statuses)
    if target is None or target == creator.status:
        return None
    try:
        validate_transition(creator.status, target)
    except InvalidTransitionError as exc:
        logger.warning(
            "Not mirroring dossier gate to creator %s: %s", creator_id, exc
        )
        return None
    creator.status = target
    await session.flush()
    return target
