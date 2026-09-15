"""Unit tests for Gate A state transitions."""

import pytest

from corp.core.models.creator import CreatorStatus
from corp.core.models.workflow import DecisionType
from corp.core.state.gates import _DECISION_TO_STATUS
from corp.core.state.machine import InvalidTransitionError, validate_transition


def test_gate_a_approve_valid():
    validate_transition(CreatorStatus.HUMAN_REVIEW, CreatorStatus.APPROVED)


def test_gate_a_reject_valid():
    validate_transition(CreatorStatus.HUMAN_REVIEW, CreatorStatus.REJECTED)


def test_gate_a_watch_valid():
    validate_transition(CreatorStatus.HUMAN_REVIEW, CreatorStatus.WATCHING)


def test_gate_a_from_wrong_state():
    with pytest.raises(InvalidTransitionError, match="Cannot transition"):
        validate_transition(CreatorStatus.DISCOVERED, CreatorStatus.APPROVED)


def test_gate_a_from_scored():
    with pytest.raises(InvalidTransitionError):
        validate_transition(CreatorStatus.SCORED, CreatorStatus.APPROVED)


def test_decision_type_maps_to_status():
    assert _DECISION_TO_STATUS[DecisionType.APPROVE] == CreatorStatus.APPROVED
    assert _DECISION_TO_STATUS[DecisionType.REJECT] == CreatorStatus.REJECTED
    assert _DECISION_TO_STATUS[DecisionType.WATCH] == CreatorStatus.WATCHING


def test_watching_can_return_to_review():
    validate_transition(CreatorStatus.WATCHING, CreatorStatus.HUMAN_REVIEW)


def test_watching_can_restart_collection():
    validate_transition(CreatorStatus.WATCHING, CreatorStatus.COLLECTING)


def test_rejected_is_terminal():
    with pytest.raises(InvalidTransitionError):
        validate_transition(CreatorStatus.REJECTED, CreatorStatus.HUMAN_REVIEW)
