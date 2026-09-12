import pytest

from corp.core.rules.loader import get_rule_version, load_yaml_rules


def test_load_scoring_rules():
    rules = load_yaml_rules("rules/scoring.yaml")
    assert "version" in rules
    assert "weights" in rules
    assert isinstance(rules["weights"], dict)


def test_load_intent_rules():
    rules = load_yaml_rules("rules/intent.yaml")
    assert "version" in rules
    assert "levels" in rules


def test_get_rule_version():
    rules = {"version": "1.0.0"}
    assert get_rule_version(rules) == "1.0.0"


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_yaml_rules("nonexistent.yaml")
