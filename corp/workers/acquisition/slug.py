"""Shared filename-safe slug helper for acquisition warmstore paths."""

import re


def slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()[:80] or "query"
