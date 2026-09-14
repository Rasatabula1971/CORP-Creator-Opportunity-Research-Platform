"""Unit tests for ResearchRun's run_type/reference validation — no database."""

import pytest

from corp.core.models.workflow import RunType
from corp.core.state.research_run import InvalidResearchRunError, validate_run_type


def test_creator_research_requires_creator_id():
    with pytest.raises(InvalidResearchRunError, match="CREATOR_RESEARCH"):
        validate_run_type(RunType.CREATOR_RESEARCH, creator_id=None, niche_id=None)


def test_creator_research_with_creator_id_is_valid():
    validate_run_type(RunType.CREATOR_RESEARCH, creator_id="c1", niche_id=None)


def test_niche_verification_requires_niche_id():
    with pytest.raises(InvalidResearchRunError, match="NICHE_VERIFICATION"):
        validate_run_type(RunType.NICHE_VERIFICATION, creator_id=None, niche_id=None)


def test_niche_verification_with_niche_id_is_valid():
    validate_run_type(RunType.NICHE_VERIFICATION, creator_id=None, niche_id="n1")


def test_niche_discovery_requires_neither():
    validate_run_type(RunType.NICHE_DISCOVERY, creator_id=None, niche_id=None)
