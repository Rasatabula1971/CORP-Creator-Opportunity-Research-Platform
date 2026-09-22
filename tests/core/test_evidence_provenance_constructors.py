"""Provenance Invariant (CORP1 Stage 4 acceptance): no Evidence row is ever
created without both ``evidence_type`` and ``origin``. Enforced statically —
every ``Evidence(...)`` constructor call anywhere under ``corp/`` must pass
both keywords explicitly."""

import ast
from pathlib import Path

import pytest

_CORP_ROOT = Path(__file__).resolve().parents[2] / "corp"
_REQUIRED = {"evidence_type", "origin"}


def _evidence_calls(path: Path) -> list[tuple[int, set[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, set[str]]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Evidence"
        ):
            found.append((node.lineno, {kw.arg for kw in node.keywords if kw.arg}))
    return found


_FILES = sorted(p for p in _CORP_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize("path", _FILES, ids=lambda p: str(p.relative_to(_CORP_ROOT)))
def test_every_evidence_constructor_sets_type_and_origin(path: Path) -> None:
    for lineno, kwargs in _evidence_calls(path):
        missing = _REQUIRED - kwargs
        assert not missing, f"{path.relative_to(_CORP_ROOT)}:{lineno} missing {sorted(missing)}"


def test_scan_actually_finds_constructors() -> None:
    total = sum(len(_evidence_calls(p)) for p in _FILES)
    assert total >= 6, total
