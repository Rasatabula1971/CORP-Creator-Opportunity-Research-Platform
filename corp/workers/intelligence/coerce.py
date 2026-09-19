"""Defensive coercion of untrusted LLM JSON values.

Model output is not shape-guaranteed for providers that rely on JSON mode
without native schema enforcement: Gemini and Groq validate post-hoc but a
field declared a number can still come back a string ("high"), null, or
missing, and a boolean can come back the string "false" (which is truthy).
These helpers never raise — a bad value falls back to the given default — so
one malformed field in one comment can't abort a whole pipeline run.
"""

from typing import Any

_FALSE_STRINGS = frozenset({"false", "0", "no", "none", "null", "off", ""})


def as_float(value: Any, default: float) -> float:
    """Coerce ``value`` to float, returning ``default`` if it isn't numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int) -> int:
    """Coerce ``value`` to int, returning ``default`` if it isn't a whole number.

    Accepts numeric strings ("3") and floats (3.0), but a non-integral string
    ("3.5") falls back — the fields this guards (counts) are conceptually ints.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def as_bool(value: Any, default: bool = False) -> bool:
    """Coerce ``value`` to bool, treating the string "false"/"0"/"no"/… as False.

    Plain ``bool(value)`` turns the string "false" into True; the model is asked
    for a JSON boolean but may emit a string, so handle both.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_STRINGS
    if value is None:
        return default
    return bool(value)
