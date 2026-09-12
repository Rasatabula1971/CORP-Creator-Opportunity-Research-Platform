from pathlib import Path
from typing import Any

import yaml


def load_yaml_rules(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Rules file must be a YAML mapping: {path}")
    return data


def get_rule_version(rules: dict[str, Any]) -> str:
    return str(rules.get("version", "unknown"))
