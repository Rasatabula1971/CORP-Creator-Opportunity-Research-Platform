from typing import Any

from corp.core.models.scoring import ConfidenceBand


def compute_confidence_band(
    source_count: int,
    evidence_depth: int,
    days_since_newest: int,
    single_source: bool,
    thresholds: dict[str, Any] | None = None,
) -> ConfidenceBand:
    """Confidence banding driven by YAML thresholds when provided.

    Args:
        thresholds: Dict with keys "high", "medium", "low", each containing
            min_sources, min_evidence, max_days_since_newest.
            Falls back to hardcoded defaults matching the YAML schema.
    """
    if thresholds is None:
        thresholds = {
            "high": {"min_sources": 3, "min_evidence": 10, "max_days_since_newest": 90},
            "medium": {"min_sources": 2, "min_evidence": 5, "max_days_since_newest": 180},
            "low": {"min_sources": 1, "min_evidence": 3},
        }

    low_cfg = thresholds.get("low", {})
    min_sources_low = low_cfg.get("min_sources", 1)
    min_evidence_low = low_cfg.get("min_evidence", 3)

    if source_count < min_sources_low or evidence_depth < min_evidence_low:
        return ConfidenceBand.INSUFFICIENT

    if single_source:
        return ConfidenceBand.LOW

    high_cfg = thresholds.get("high", {})
    if (
        source_count >= high_cfg.get("min_sources", 3)
        and evidence_depth >= high_cfg.get("min_evidence", 10)
        and days_since_newest < high_cfg.get("max_days_since_newest", 90)
    ):
        return ConfidenceBand.HIGH

    med_cfg = thresholds.get("medium", {})
    max_days_medium = med_cfg.get("max_days_since_newest", 180)
    if days_since_newest <= max_days_medium:
        if (
            source_count >= med_cfg.get("min_sources", 2)
            and evidence_depth >= med_cfg.get("min_evidence", 5)
        ):
            return ConfidenceBand.MEDIUM

    return ConfidenceBand.LOW
