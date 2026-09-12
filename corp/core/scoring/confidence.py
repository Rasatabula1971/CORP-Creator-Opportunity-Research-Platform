from corp.core.models.scoring import ConfidenceBand


def compute_confidence_band(
    source_count: int,
    evidence_depth: int,
    days_since_newest: int,
    single_source: bool,
) -> ConfidenceBand:
    """Adapted from CIP EOR banding pattern."""
    if source_count < 1 or evidence_depth < 3:
        return ConfidenceBand.INSUFFICIENT

    if single_source:
        return ConfidenceBand.LOW

    if days_since_newest > 365:
        return ConfidenceBand.LOW

    if source_count >= 3 and evidence_depth >= 10 and days_since_newest < 90:
        return ConfidenceBand.HIGH

    return ConfidenceBand.MEDIUM
