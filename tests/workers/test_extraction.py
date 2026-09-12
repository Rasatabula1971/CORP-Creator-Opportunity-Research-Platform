"""Unit tests for problem extraction — LLM calls mocked."""

import pytest

from corp.workers.intelligence.extraction import (
    EXTRACTION_PROMPT_VERSION,
    ExtractedObservation,
    extract_observations,
)
from corp.workers.providers.registry import LLMProvider


class FakeProvider(LLMProvider):
    """Returns canned JSON responses."""

    def __init__(self, response: dict | None = None) -> None:
        self._response = response or {
            "observations": [
                {
                    "text": "Viewer struggles with battery life",
                    "category": "problem",
                    "is_inferred": False,
                    "confidence": 0.9,
                },
                {
                    "text": "Where can I buy the charger?",
                    "category": "question",
                    "is_inferred": False,
                    "confidence": 0.85,
                },
            ]
        }

    @property
    def model_name(self) -> str:
        return "fake-model-v1"

    async def generate_json(self, prompt: str, system: str | None = None) -> dict:
        return self._response


class FailingProvider(LLMProvider):
    @property
    def model_name(self) -> str:
        return "failing-model"

    async def generate_json(self, prompt: str, system: str | None = None) -> dict:
        raise RuntimeError("API exploded")


async def test_extract_observations_basic():
    provider = FakeProvider()
    obs = await extract_observations(
        provider=provider,
        comment_text="Battery dies too fast. Where can I buy the charger?",
        author="viewer1",
        content_title="Phone Review",
    )
    assert len(obs) == 2
    assert all(isinstance(o, ExtractedObservation) for o in obs)
    assert obs[0].category == "problem"
    assert obs[1].category == "question"
    assert obs[0].confidence == 0.9
    assert obs[0].is_inferred is False


async def test_extract_observations_empty_comment():
    provider = FakeProvider({"observations": []})
    obs = await extract_observations(
        provider=provider,
        comment_text="Nice video!",
        author="viewer2",
        content_title="Vlog",
    )
    assert obs == []


async def test_extract_observations_malformed_response():
    provider = FakeProvider({"observations": [{"no_text_key": True}, "garbage"]})
    obs = await extract_observations(
        provider=provider,
        comment_text="some comment",
        author=None,
        content_title=None,
    )
    assert obs == []


async def test_extract_observations_clamps_confidence():
    provider = FakeProvider(
        {"observations": [{"text": "X", "confidence": 5.0, "category": "problem"}]}
    )
    obs = await extract_observations(provider=provider, comment_text="X", author=None, content_title=None)
    assert obs[0].confidence == 1.0


async def test_extract_observations_negative_confidence():
    provider = FakeProvider(
        {"observations": [{"text": "Y", "confidence": -0.5, "category": "problem"}]}
    )
    obs = await extract_observations(provider=provider, comment_text="Y", author=None, content_title=None)
    assert obs[0].confidence == 0.0


async def test_extract_observations_provider_failure():
    provider = FailingProvider()
    obs = await extract_observations(
        provider=provider,
        comment_text="Some text",
        author="a",
        content_title="b",
    )
    assert obs == []


async def test_extract_observations_text_truncation():
    long_text = "A" * 5000
    provider = FakeProvider({"observations": [{"text": long_text, "category": "problem"}]})
    obs = await extract_observations(provider=provider, comment_text=long_text, author=None, content_title=None)
    assert len(obs[0].text) == 500


async def test_prompt_version_constant():
    assert EXTRACTION_PROMPT_VERSION == "extract_v1"


async def test_is_inferred_flag_preserved():
    provider = FakeProvider({
        "observations": [
            {"text": "Inferred insight", "category": "problem", "is_inferred": True, "confidence": 0.6}
        ]
    })
    obs = await extract_observations(provider=provider, comment_text="x", author=None, content_title=None)
    assert obs[0].is_inferred is True
