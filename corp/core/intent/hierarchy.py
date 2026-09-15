import re
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


def _matches_keyword(text: str, keyword: str) -> bool:
    """Whole-word/phrase match, case-insensitive.

    A bare substring test made "vs" fire on "devs"/"tvs" and "compared" on
    "comparedto"; because the rules result is a floor the LLM cannot lower, one
    such comment forced a whole cluster to VALIDATION and inflated its commercial
    intent score. The lookarounds require the match not be flanked by word
    characters, so multi-word phrases and keywords with punctuation still work.
    """
    return (
        re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text, re.IGNORECASE)
        is not None
    )


def classify_signal_level(indicators: list[str], rules: dict[str, Any]) -> SignalLevel:
    """Rules-table classification. Match indicators against the hierarchy."""
    levels = rules.get("levels", {})
    for level_name in ["validation", "strong", "moderate", "weak"]:
        level_config = levels.get(level_name, {})
        keywords = [kw for kw in level_config.get("keywords", []) if kw]
        for indicator in indicators:
            if any(_matches_keyword(indicator, kw) for kw in keywords):
                return SignalLevel(level_name)
    return SignalLevel.WEAK
