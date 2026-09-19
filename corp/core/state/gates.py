"""Gate A logic — human review decisions with state machine transitions."""

from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.scoring import OpportunityScore
from corp.core.models.workflow import DecisionType, Gate, HumanDecision
from corp.core.state.machine import validate_transition

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
