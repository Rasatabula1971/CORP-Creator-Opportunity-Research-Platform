"""Unit tests for the LLM provider registry."""

import json

import pytest

from corp.workers.providers.registry import GeminiProvider, LLMProvider, _response_hash


async def test_llm_provider_is_abstract():
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


async def test_response_hash_deterministic():
    data = {"key": "value", "num": 42}
    h1 = _response_hash(data)
    h2 = _response_hash(data)
    assert h1 == h2
    assert len(h1) == 16


async def test_response_hash_order_independent():
    h1 = _response_hash({"a": 1, "b": 2})
    h2 = _response_hash({"b": 2, "a": 1})
    assert h1 == h2


async def test_concrete_provider_satisfies_interface():
    class TestProvider(LLMProvider):
        @property
        def model_name(self) -> str:
            return "test-v1"

        async def generate_json(self, prompt: str, system: str | None = None) -> dict:
            return {"result": True}

    p = TestProvider()
    assert p.model_name == "test-v1"
    result = await p.generate_json("hello")
    assert result == {"result": True}
