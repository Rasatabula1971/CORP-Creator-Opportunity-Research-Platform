import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


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
