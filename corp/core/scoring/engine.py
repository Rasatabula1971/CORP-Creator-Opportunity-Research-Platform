import hashlib
import json
import math
from pathlib import Path
from typing import Any

import yaml

from corp.core.models.competitive import CompetitorStrength
from corp.core.models.intent import SignalLevel


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def load_scoring_rules(rules_path: str) -> dict[str, Any]:
    path = Path(rules_path)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Scoring rules not found: {path}")
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
        band = bands.get(band_key, {})
        if aggregate >= band.get("min", 0.0):
            return band.get("label", band_key)
    return "Weak — insufficient signal"


# ── Component score calculators ──────────────────────────────────────


_LEVEL_NUMERIC = {
    SignalLevel.WEAK: 0.15,
    SignalLevel.MODERATE: 0.45,
    SignalLevel.STRONG: 0.75,
    SignalLevel.VALIDATION: 0.95,
}


def score_audience_problem_frequency(frequency: int, cap: int = 100) -> float:
    if frequency <= 0:
        return 0.0
    return min(1.0, math.log1p(frequency) / math.log1p(cap))


def score_recency_trend(recency_score: float) -> float:
    return max(0.0, min(1.0, recency_score))


def score_commercial_intent(level: SignalLevel, confidence: float) -> float:
    base = _LEVEL_NUMERIC.get(level, 0.15)
    return base * max(0.0, min(1.0, confidence))


def score_evidence_depth(observation_count: int, cap: int = 50) -> float:
    if observation_count <= 0:
        return 0.0
    return min(1.0, math.log1p(observation_count) / math.log1p(cap))


def score_creator_reach(subscriber_count: int | None) -> float:
    if not subscriber_count or subscriber_count <= 0:
        return 0.0
    return min(1.0, math.log10(max(1, subscriber_count)) / 7.0)


_STRENGTH_WEIGHT = {
    CompetitorStrength.WEAK: 0.25,
    CompetitorStrength.MODERATE: 0.6,
    CompetitorStrength.STRONG: 1.0,
}
_SATURATION_CAP = 3.0  # pressure at which the market counts as fully saturated


def score_competition_saturation(competitors: list[CompetitorStrength] | None = None) -> float:
    """Higher = more whitespace (less saturated), matching the "higher is better"
    convention of the other components. Neutral 0.5 when no competitor research
    has been done yet for this cluster — not evidence of an open market."""
    if not competitors:
        return 0.5
    pressure = sum(_STRENGTH_WEIGHT.get(c, 0.5) for c in competitors)
    saturation = min(1.0, pressure / _SATURATION_CAP)
    return round(1.0 - saturation, 4)
