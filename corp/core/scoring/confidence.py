from typing import Any

from corp.core.models.scoring import ConfidenceBand


def compute_confidence_band(
    source_count: int,
    evidence_depth: int,
    days_since_newest: int,
    single_source: bool,
    thresholds: dict[str, Any],
) -> ConfidenceBand:
    """Adapted from CIP EOR banding pattern.

    ``thresholds`` is rules/scoring.yaml's ``confidence_thresholds`` section
    (``{"high": {...}, "medium": {...}, "low": {...}}``), passed in rather
    than hardcoded here so the YAML stays the single source of truth. A
    missing tier or key falls back to that tier's documented default.
    """
    low = thresholds.get("low", {})
    if source_count < 1 or evidence_depth < low.get("min_evidence", 3):
        return ConfidenceBand.INSUFFICIENT

    if single_source:
        return ConfidenceBand.LOW

    high = thresholds.get("high", {})
    if (
        source_count >= high.get("min_sources", 3)
        and evidence_depth >= high.get("min_evidence", 10)
        and days_since_newest < high.get("max_days_since_newest", 90)
    ):
        return ConfidenceBand.HIGH

    medium = thresholds.get("medium", {})
    if (
        source_count >= medium.get("min_sources", 2)
        and evidence_depth >= medium.get("min_evidence", 5)
        and days_since_newest < medium.get("max_days_since_newest", 180)
    ):
        return ConfidenceBand.MEDIUM

    return ConfidenceBand.LOW
