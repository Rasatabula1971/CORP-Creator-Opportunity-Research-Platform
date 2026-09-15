"""Unit tests for creator-side extraction — LLM mocked."""

import pytest

from corp.workers.intelligence.creator_content import (
    CREATOR_PROMPT_VERSION,
    extract_creator_problems,
)
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.providers.registry import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, response):
        self._response = response
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake"

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
        self.prompts.append(prompt)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


async def test_extracts_and_normalises():
    provider = FakeProvider({"observations": [
        {"text": "Desks wobble on uneven floors", "category": "problem", "confidence": 1.7},
        {"text": "", "category": "problem"},
        "not a dict",
    ]})
    obs = await extract_creator_problems(provider, "Fix a wobbly desk", "Full walkthrough")
    assert len(obs) == 1
    assert obs[0].text == "Desks wobble on uneven floors"
    assert obs[0].confidence == 1.0
    assert obs[0].is_inferred is False
    assert "Fix a wobbly desk" in provider.prompts[0]
    assert "Full walkthrough" in provider.prompts[0]


async def test_body_is_truncated():
    provider = FakeProvider({"observations": []})
    await extract_creator_problems(provider, "t", "x" * 10_000, max_body_chars=100)
    assert "x" * 100 in provider.prompts[0]
    assert "x" * 101 not in provider.prompts[0]


async def test_non_list_output_is_empty():
    provider = FakeProvider({"observations": {"text": "oops"}})
    assert await extract_creator_problems(provider, "t", "b") == []


async def test_failure_raises_typed_error():
    provider = FakeProvider(RuntimeError("down"))
    with pytest.raises(LLMCallError, match="creator_extraction: down"):
        await extract_creator_problems(provider, "t", "b")


def test_prompt_version_pinned():
    assert CREATOR_PROMPT_VERSION == "creator_v1"
