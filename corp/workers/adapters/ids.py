"""Stable external ids for content that has no native id.

Python's built-in ``hash()`` is salted per process (PYTHONHASHSEED), so an
id derived from it changes on every worker start and dedupe never matches.
Use a content hash instead so the same item maps to the same id across runs.
"""

import hashlib


def stable_id(prefix: str, *parts: str | None) -> str:
    """Return ``prefix`` + 16 hex chars derived from ``parts`` (case-insensitive)."""
    joined = "|".join((p or "").strip().casefold() for p in parts)
    return prefix + hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
