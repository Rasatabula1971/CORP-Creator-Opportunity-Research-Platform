from corp.core.models.creator import CreatorStatus

VALID_TRANSITIONS: dict[CreatorStatus, set[CreatorStatus]] = {
    CreatorStatus.DISCOVERED: {CreatorStatus.COLLECTING},
    CreatorStatus.COLLECTING: {CreatorStatus.COLLECTED},
    CreatorStatus.COLLECTED: {CreatorStatus.EXTRACTING},
    CreatorStatus.EXTRACTING: {CreatorStatus.EXTRACTED},
    CreatorStatus.EXTRACTED: {CreatorStatus.CLUSTERING},
    CreatorStatus.CLUSTERING: {CreatorStatus.CLUSTERED},
    CreatorStatus.CLUSTERED: {CreatorStatus.SCORING},
    CreatorStatus.SCORING: {CreatorStatus.SCORED},
    CreatorStatus.SCORED: {CreatorStatus.RESEARCH_COMPLETE},
    CreatorStatus.RESEARCH_COMPLETE: {CreatorStatus.DOSSIER_GENERATED},
    CreatorStatus.DOSSIER_GENERATED: {CreatorStatus.HUMAN_REVIEW},
    CreatorStatus.HUMAN_REVIEW: {
        CreatorStatus.APPROVED,
        CreatorStatus.REJECTED,
        CreatorStatus.WATCHING,
    },
    CreatorStatus.APPROVED: {CreatorStatus.OUTREACH_READY},
    # A watched creator can be re-reviewed, re-researched (R12), or decided
    # straight from its watched dossier (the dossier gate accepts decisions
    # on WATCHING dossiers), so the two terminal gate outcomes are legal here.
    CreatorStatus.WATCHING: {
        CreatorStatus.HUMAN_REVIEW,
        CreatorStatus.COLLECTING,
        CreatorStatus.APPROVED,
        CreatorStatus.REJECTED,
    },
    CreatorStatus.OUTREACH_READY: {CreatorStatus.IN_OUTREACH},
    CreatorStatus.IN_OUTREACH: {CreatorStatus.PARTNERSHIP, CreatorStatus.REJECTED},
    CreatorStatus.REJECTED: set(),
    CreatorStatus.PARTNERSHIP: set(),
}


class InvalidTransitionError(Exception):
    pass


def validate_transition(current: CreatorStatus, target: CreatorStatus) -> None:
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from {current.value} to {target.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
