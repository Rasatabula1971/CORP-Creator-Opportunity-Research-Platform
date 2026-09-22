import pytest

from corp.core.models.creator import CreatorStatus
from corp.core.state.machine import InvalidTransitionError, validate_transition


def test_valid_transition():
    validate_transition(CreatorStatus.DISCOVERED, CreatorStatus.COLLECTING)


def test_valid_gate_transitions():
    validate_transition(CreatorStatus.HUMAN_REVIEW, CreatorStatus.APPROVED)
    validate_transition(CreatorStatus.HUMAN_REVIEW, CreatorStatus.REJECTED)
    validate_transition(CreatorStatus.HUMAN_REVIEW, CreatorStatus.WATCHING)


def test_invalid_transition():
    with pytest.raises(InvalidTransitionError):
        validate_transition(CreatorStatus.DISCOVERED, CreatorStatus.APPROVED)


def test_rejected_is_terminal():
    with pytest.raises(InvalidTransitionError):
        validate_transition(CreatorStatus.REJECTED, CreatorStatus.DISCOVERED)


def test_watching_allows_re_review():
    validate_transition(CreatorStatus.WATCHING, CreatorStatus.HUMAN_REVIEW)
    validate_transition(CreatorStatus.WATCHING, CreatorStatus.COLLECTING)


def test_watching_can_be_decided_from_its_dossier():
    """R12b: the dossier gate accepts decisions on WATCHING dossiers, so the
    creator mirror needs WATCHING -> APPROVED / REJECTED to be legal."""
    validate_transition(CreatorStatus.WATCHING, CreatorStatus.APPROVED)
    validate_transition(CreatorStatus.WATCHING, CreatorStatus.REJECTED)
