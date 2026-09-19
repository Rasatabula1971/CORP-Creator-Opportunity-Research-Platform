import hashlib
import json
import math
from pathlib import Path
from typing import Any

import yaml

from corp.core.models.intent import SignalLevel


def load_scoring_rules(rules_path: str) -> dict[str, Any]:
    path = Path(rules_path)
    if not path.exists():
        raise FileNotFoundError(f"Scoring rules not found: {rules_path}")
    with open(path) as f:
        return yaml.safe_load(f)


def compute_score(
    component_scores: dict[str, float], weights: dict[str, float]
) -> float:
    total_weight = sum(weights.get(k, 0.0) for k in component_scores)
    if total_weight == 0:
        return 0.0
    return sum(
        component_scores[k] * weights.get(k, 0.0) for k in component_scores
    ) / total_weight


def compute_hash(component_scores: dict[str, float], rule_version: str) -> str:
    """Deterministic hash: same inputs → same hash. Adapted from CIP Step 9."""
    payload = json.dumps(
        {"components": component_scores, "rule_version": rule_version},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_score_band(aggregate: float, rules: dict[str, Any]) -> str:
    bands = rules.get("score_bands", {})
    for band_key in ("exceptional", "strong", "moderate", "weak"):
        band = bands.get(band_key)
        # A band with no explicit "min" must not match: defaulting it to 0.0
        # made a missing high band swallow every score into that label.
        if not band or "min" not in band:
            continue
        if aggregate >= band["min"]:
            return band.get("label", band_key)
    return "Weak — insufficient signal"


# ── Component score calculators ──────────────────────────────────────


# Mirrors the `weight` field of each level in rules/intent.yaml.
_LEVEL_NUMERIC = {
    SignalLevel.WEAK: 0.25,
    SignalLevel.MODERATE: 0.50,
    SignalLevel.STRONG: 0.75,
    SignalLevel.VALIDATION: 1.0,
}


def score_audience_problem_frequency(frequency: int, cap: int = 100) -> float:
    if frequency <= 0:
        return 0.0
    return min(1.0, math.log1p(frequency) / math.log1p(cap))


def score_recency_trend(recency_score: float) -> float:
    return max(0.0, min(1.0, recency_score))


def score_commercial_intent(level: SignalLevel, confidence: float) -> float:
    base = _LEVEL_NUMERIC.get(level, 0.25)
    return base * max(0.0, min(1.0, confidence))


def score_evidence_depth(observation_count: int, cap: int = 50) -> float:
    if observation_count <= 0:
        return 0.0
    return min(1.0, math.log1p(observation_count) / math.log1p(cap))


def score_creator_reach(subscriber_count: int | None) -> float:
    if not subscriber_count or subscriber_count <= 0:
        return 0.0
    return min(1.0, math.log10(max(1, subscriber_count)) / 7.0)


# ── v2 components (scoring_v2) ───────────────────────────────────────

# Evidence gathered through official APIs counts fully; open public feeds a
# little less; anything that had to work around a platform's terms, half.
ACCESS_WEIGHTS: dict[str, float] = {"official": 1.0, "open": 0.8, "vendor_scrape": 0.5}


def weighted_evidence_count(counts_by_access_method: dict[str, int]) -> float:
    """Evidence depth input: observation counts weighted by how they were obtained."""
    return sum(
        max(0, n) * ACCESS_WEIGHTS.get(method, 0.5)
        for method, n in counts_by_access_method.items()
    )


def growth_ratio(earliest: int | None, latest: int | None) -> float | None:
    """Relative growth between two snapshot values; None when not measurable."""
    if earliest is None or latest is None or earliest <= 0:
        return None
    return (latest - earliest) / earliest


def score_engagement_velocity(growth: float | None) -> float:
    """0.5 = flat or unknown; strong growth → 1.0; decline → toward 0."""
    if growth is None:
        return 0.5
    return max(0.0, min(1.0, 0.5 + 0.5 * math.tanh(2.0 * growth)))


def score_competition_saturation(
    commerce_overlap: float | None = None,
    commerce_signal_count: int = 0,
) -> float:
    """Higher = less saturated = more room for a new product.

    ``commerce_overlap`` is how much the cluster's problem already appears on
    the creator's shop / course / product pages (0..1). ``commerce_signal_count``
    is how many monetisation signals the creator's web presence shows at all.
    With no creator-web evidence the score is a neutral 0.5.
    """
    if commerce_overlap is None:
        return 0.5
    overlap = max(0.0, min(1.0, commerce_overlap))
    penalty = 0.7 * overlap + 0.05 * max(0, commerce_signal_count)
    return max(0.0, min(1.0, 1.0 - penalty))


def score_creator_content_alignment(
    matching_creator_observations: int, saturate_at: int = 3
) -> float:
    """How much the creator already talks about this problem in their own content."""
    if matching_creator_observations <= 0:
        return 0.0
    return min(1.0, matching_creator_observations / saturate_at)


def score_cross_platform_consistency(platforms_with_problem: int, total_platforms: int) -> float:
    """Fraction of the creator's audience platforms where the problem shows up.

    Neutral 0.5 when there is only one platform to compare against.
    """
    if total_platforms <= 1:
        return 0.5
    return max(0.0, min(1.0, platforms_with_problem / total_platforms))
