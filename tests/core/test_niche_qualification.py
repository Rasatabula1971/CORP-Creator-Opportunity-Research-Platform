import pytest

from corp.core.scoring.niche_qualification import (
    NicheInput,
    compute_research_completeness,
    load_rules,
)

FULL = NicheInput(
    evidence_count=10,
    author_count=5,
    is_broad_domain=False,
    creator_count_observed=10,
    target_band_creator_count=3,
)
PARTIAL = NicheInput(
    evidence_count=10,
    author_count=5,
    is_broad_domain=False,
    creator_count_observed=0,
    target_band_creator_count=0,
)


def test_all_four_stages_from_yaml_order():
    rules = {
        "completeness_stages": [
            "has_evidence",
            "is_verified",
            "has_ecosystem_data",
            "has_target_band_data",
        ]
    }
    assert compute_research_completeness(FULL, True, rules) == 1.0
    assert compute_research_completeness(PARTIAL, True, rules) == 0.5


def test_custom_subset_of_stages_is_respected():
    """Changing completeness_stages in the YAML must change the result —
    this was previously dead config; the function ignored it entirely."""
    rules = {"completeness_stages": ["has_evidence", "is_verified"]}
    assert compute_research_completeness(PARTIAL, True, rules) == 1.0
    assert compute_research_completeness(PARTIAL, False, rules) == 0.5


def test_missing_completeness_stages_falls_back_to_all_four():
    assert compute_research_completeness(FULL, True, {}) == 1.0
    assert compute_research_completeness(PARTIAL, True, {}) == 0.5


def test_unknown_stage_names_are_ignored():
    rules = {"completeness_stages": ["has_evidence", "not_a_real_stage"]}
    assert compute_research_completeness(FULL, True, rules) == 1.0


def test_load_rules_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_rules(str(tmp_path / "does_not_exist.yaml"))


def test_load_rules_non_mapping_yaml_raises_value_error(tmp_path):
    """An empty or truncated YAML file parses to None, not a dict — without
    validation this surfaced as an unhelpful AttributeError two calls later
    (rules.get(...) on None) instead of a clear error at load time."""
    bad = tmp_path / "not_a_mapping.yaml"
    bad.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_rules(str(bad))


def test_load_rules_empty_file_raises_value_error(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_rules(str(empty))
