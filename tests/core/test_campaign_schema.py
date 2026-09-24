"""CampaignCreate validation: every number drives real automated work."""

import pytest
from pydantic import ValidationError

from corp.core.schemas.campaign import (
    MAX_CREATORS_PER_NICHE,
    MAX_HUMAN_GATE_CAPACITY,
    MAX_TARGET_NICHE_COUNT,
    CampaignCreate,
)


def test_defaults_are_valid():
    body = CampaignCreate(name="Defaults")
    assert (body.creator_min_followers, body.creator_max_followers) == (10_000, 200_000)


@pytest.mark.parametrize(
    "field, value",
    [
        ("target_niche_count", 0),
        ("target_niche_count", -1),
        ("target_niche_count", MAX_TARGET_NICHE_COUNT + 1),
        ("initial_creators_per_niche", 0),
        ("initial_creators_per_niche", MAX_CREATORS_PER_NICHE + 1),
        ("human_gate_capacity", 0),
        ("human_gate_capacity", MAX_HUMAN_GATE_CAPACITY + 1),
        ("creator_min_followers", -1),
        ("creator_max_followers", 0),
    ],
)
def test_out_of_range_counts_are_rejected(field, value):
    with pytest.raises(ValidationError) as info:
        CampaignCreate(name="Bad", **{field: value})
    assert field in str(info.value)


def test_inverted_follower_band_is_rejected():
    """min > max is not a strict filter, it is a campaign that can never
    onboard a creator and so never produces a dossier."""
    with pytest.raises(ValidationError) as info:
        CampaignCreate(name="Inverted", creator_min_followers=50_000, creator_max_followers=1_000)
    assert "creator_min_followers must not exceed creator_max_followers" in str(info.value)


def test_equal_band_bounds_are_allowed():
    body = CampaignCreate(name="Point", creator_min_followers=5_000, creator_max_followers=5_000)
    assert body.creator_min_followers == body.creator_max_followers == 5_000


def test_zero_minimum_means_no_floor():
    assert CampaignCreate(name="Open", creator_min_followers=0).creator_min_followers == 0


@pytest.mark.parametrize("name", ["", "x" * 256])
def test_name_length_is_bounded(name):
    with pytest.raises(ValidationError):
        CampaignCreate(name=name)
