"""No-DB tests for the Campaign row -> stage config mapping.

Audit finding: Campaign.target_niche_count, initial_creators_per_niche,
creator_min/max_followers and human_gate_capacity were stored and echoed
by the API but never read by any pipeline stage -- every campaign ran with
the worker dataclass defaults. These tests pin each field to the stage
config it must drive.
"""

from corp.core.models.campaign import Campaign
from corp.workers.campaign_config import (
    eco_config,
    onboard_config,
    selection_config,
    stage_configs,
)


def _campaign(**overrides: int) -> Campaign:
    fields = {
        "target_niche_count": 3,
        "initial_creators_per_niche": 4,
        "creator_min_followers": 25_000,
        "creator_max_followers": 90_000,
        "human_gate_capacity": 12,
    }
    fields.update(overrides)
    return Campaign(name="Configured", **fields)


def test_target_niche_count_is_the_selection_cap() -> None:
    cfg = selection_config(_campaign(target_niche_count=3))
    assert cfg.top_n == 3
    assert cfg.min_score == 0.0
    assert cfg.min_confidence == 0.0


def test_follower_band_drives_the_ecosystem_estimate() -> None:
    cfg = eco_config(_campaign())
    assert (cfg.min_followers, cfg.max_followers) == (25_000, 90_000)


def test_onboarding_takes_band_and_per_niche_cap() -> None:
    cfg = onboard_config(_campaign(initial_creators_per_niche=4))
    assert cfg.max_creators_per_niche == 4
    assert (cfg.min_followers, cfg.max_followers) == (25_000, 90_000)
    # Default search depth is kept for small caps ...
    assert cfg.search_count == 20


def test_onboarding_search_depth_grows_with_a_large_cap() -> None:
    # ... and scales so the band filter never starves a big cap.
    cfg = onboard_config(_campaign(initial_creators_per_niche=30))
    assert cfg.max_creators_per_niche == 30
    assert cfg.search_count == 60


def test_stage_configs_bundle_matches_the_individual_mappings() -> None:
    campaign = _campaign()
    bundle = stage_configs(campaign)
    assert bundle.selection == selection_config(campaign)
    assert bundle.ecosystem == eco_config(campaign)
    assert bundle.onboarding == onboard_config(campaign)
