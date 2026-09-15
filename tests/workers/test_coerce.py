"""Unit tests for defensive LLM-output coercion + parse-path regressions."""

from unittest.mock import AsyncMock

import pytest

from corp.workers.intelligence.coerce import as_bool, as_float, as_int
from corp.workers.intelligence.extraction import extract_observations
from corp.workers.intelligence.creator_content import extract_creator_problems
from corp.workers.intelligence.topics import classify_topics


# ── as_float ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.8, 0.8),
        ("0.8", 0.8),
        (1, 1.0),
        ("high", 0.5),   # non-numeric string → default
        (None, 0.5),      # null → default
        ("", 0.5),
        ([], 0.5),
    ],
)
def test_as_float(value, expected):
    assert as_float(value, 0.5) == expected


# ── as_int ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        (3, 3),
        ("3", 3),
        (3.0, 3),
        ("3.5", 3),   # numeric string, truncated
        (2.9, 2),
        ("lots", 0),   # non-numeric → default
        (None, 0),
    ],
)
def test_as_int(value, expected):
    assert as_int(value, 0) == expected


# ── as_bool ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        ("true", True),
        ("false", False),   # the bug: bool("false") is True
        ("False", False),
        ("0", False),
        ("no", False),
        ("", False),
        ("yes", True),
        (1, True),
        (0, False),
        (None, False),
    ],
)
def test_as_bool(value, expected):
    assert as_bool(value, False) is expected


# ── parse-path regressions: malformed model output must not crash ────


def _provider(payload: dict) -> AsyncMock:
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=payload)
    return provider


async def test_extraction_survives_bad_confidence_and_bool():
    provider = _provider({
        "observations": [
            {"text": "app keeps crashing", "confidence": "high", "is_inferred": "false"},
        ]
    })
    out = await extract_observations(provider, "app keeps crashing", None, None)
    assert len(out) == 1
    assert out[0].confidence == 0.5      # "high" → default, not a crash
    assert out[0].is_inferred is False   # "false" → False, not truthy True


async def test_creator_content_survives_bad_values():
    provider = _provider({
        "observations": [
            {"text": "I cover X", "confidence": None, "is_inferred": "true"},
        ]
    })
    out = await extract_creator_problems(provider, "title", "desc")
    assert len(out) == 1
    assert out[0].confidence == 0.5
    assert out[0].is_inferred is True


async def test_topics_survives_bad_numbers():
    provider = _provider({
        "topics": [
            {"name": "python", "confidence": "very", "evidence_count": "many"},
        ]
    })
    out = await classify_topics(provider, [{"title": "t"}])
    assert len(out) == 1
    assert out[0]["confidence"] == 0.5
    assert out[0]["evidence_count"] == 0
