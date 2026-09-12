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
