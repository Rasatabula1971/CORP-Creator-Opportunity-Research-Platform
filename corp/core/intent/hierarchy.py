from pathlib import Path
from typing import Any

import yaml

from corp.core.models.intent import SignalLevel


def load_intent_rules(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Intent rules not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def classify_signal_level(indicators: list[str], rules: dict[str, Any]) -> SignalLevel:
    """Rules-table classification. Match indicators against the hierarchy."""
    levels = rules.get("levels", {})
    for level_name in ["validation", "strong", "moderate", "weak"]:
        level_config = levels.get(level_name, {})
        keywords = level_config.get("keywords", [])
        for indicator in indicators:
            indicator_lower = indicator.lower()
            if any(kw.lower() in indicator_lower for kw in keywords):
                return SignalLevel(level_name)
    return SignalLevel.WEAK
