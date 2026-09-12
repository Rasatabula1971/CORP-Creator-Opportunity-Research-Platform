from corp.core.models.scoring import ConfidenceBand
from corp.core.scoring.confidence import compute_confidence_band


def test_insufficient_no_sources():
    assert compute_confidence_band(0, 10, 30, False) == ConfidenceBand.INSUFFICIENT


def test_insufficient_low_evidence():
    assert compute_confidence_band(3, 2, 30, False) == ConfidenceBand.INSUFFICIENT


def test_low_single_source():
    assert compute_confidence_band(1, 10, 30, True) == ConfidenceBand.LOW


def test_low_stale_data():
    assert compute_confidence_band(3, 10, 400, False) == ConfidenceBand.LOW


def test_high_confidence():
    assert compute_confidence_band(3, 10, 30, False) == ConfidenceBand.HIGH


def test_medium_confidence():
    assert compute_confidence_band(2, 5, 100, False) == ConfidenceBand.MEDIUM


def test_custom_thresholds_override_defaults():
    custom = {
        "high": {"min_sources": 5, "min_evidence": 20, "max_days_since_newest": 30},
        "medium": {"min_sources": 3, "min_evidence": 10, "max_days_since_newest": 90},
        "low": {"min_sources": 1, "min_evidence": 3},
    }
    assert compute_confidence_band(3, 10, 30, False, thresholds=custom) == ConfidenceBand.MEDIUM
    assert compute_confidence_band(5, 20, 20, False, thresholds=custom) == ConfidenceBand.HIGH
    assert compute_confidence_band(2, 5, 200, False, thresholds=custom) == ConfidenceBand.LOW
