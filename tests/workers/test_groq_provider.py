"""Unit tests for the Groq provider — HTTP mocked, no network."""

import json

import httpx
import pytest

from corp.workers.providers.errors import (
    ProviderError,
    ProviderExhaustedError,
    ProviderUnavailableError,
)
from corp.workers.providers.groq import GroqProvider
from corp.workers.providers.registry import LLMProvider


def _completion(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _provider(handler, **kw) -> GroqProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer k"}
    )
    kw.setdefault("retry_wait_min", 0.001)
    kw.setdefault("retry_wait_max", 0.001)
    return GroqProvider(api_key="k", client=client, **kw)


def _capture(response: httpx.Response):
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return handler, seen


async def test_is_llm_provider_and_model_name():
    handler, _ = _capture(httpx.Response(200, json=_completion("{}")))
    p = _provider(handler, model="openai/gpt-oss-20b")
    assert isinstance(p, LLMProvider)
    assert p.model_name == "groq/openai/gpt-oss-20b"


async def test_success_sends_json_mode_and_parses():
    handler, seen = _capture(httpx.Response(200, json=_completion('{"topics": ["a"]}')))
    result = await _provider(handler).generate_json("Return JSON for x", system="Be terse. JSON.")
    assert result == {"topics": ["a"]}

    req = seen[0]
    assert req.url.path.endswith("/chat/completions")
    assert req.headers["authorization"] == "Bearer k"
    body = json.loads(req.content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["messages"][0] == {"role": "system", "content": "Be terse. JSON."}
    assert body["messages"][1] == {"role": "user", "content": "Return JSON for x"}
    assert body["stream"] is False


async def test_json_instruction_added_when_prompt_lacks_the_word():
    handler, seen = _capture(httpx.Response(200, json=_completion("{}")))
    await _provider(handler).generate_json("summarise this", system="Be terse.")
    system = json.loads(seen[0].content)["messages"][0]["content"]
    assert "JSON" in system  # Groq's json_object mode requires it in the conversation


async def test_output_budget_and_reasoning_effort_are_sent():
    handler, seen = _capture(httpx.Response(200, json=_completion("{}")))
    await _provider(handler, max_output_tokens=2048, reasoning_effort="low").generate_json("x")
    body = json.loads(seen[0].content)
    assert body["max_completion_tokens"] == 2048
    assert body["reasoning_effort"] == "low"


async def test_no_reasoning_effort_omits_the_field():
    """Non-reasoning models reject the parameter, so None/"" must not send it."""
    handler, seen = _capture(httpx.Response(200, json=_completion("{}")))
    await _provider(handler, reasoning_effort="").generate_json("x")
    assert "reasoning_effort" not in json.loads(seen[0].content)


async def test_default_system_prompt_already_mentions_json():
    handler, seen = _capture(httpx.Response(200, json=_completion("{}")))
    await _provider(handler).generate_json("summarise this")
    system = json.loads(seen[0].content)["messages"][0]["content"]
    assert system.count("JSON") == 1


async def test_code_fenced_json_is_stripped():
    handler, _ = _capture(httpx.Response(200, json=_completion('```json\n{"ok": 1}\n```')))
    assert await _provider(handler).generate_json("x") == {"ok": 1}


async def test_429_with_retry_after_is_exhausted_not_daily():
    handler, seen = _capture(
        httpx.Response(
            429,
            headers={"retry-after": "12", "x-ratelimit-remaining-requests": "7"},
            json={"error": {"message": "Rate limit reached"}},
        )
    )
    with pytest.raises(ProviderExhaustedError) as info:
        await _provider(handler).generate_json("x")
    assert info.value.retry_after == 12.0
    assert info.value.daily is False
    assert info.value.provider == "groq/openai/gpt-oss-20b"
    assert "Rate limit reached" in str(info.value)
    assert len(seen) == 1  # a 429 is never retried inside the call


async def test_429_with_zero_remaining_is_daily():
    handler, _ = _capture(
        httpx.Response(429, headers={"x-ratelimit-remaining-requests": "0"}, json={})
    )
    with pytest.raises(ProviderExhaustedError) as info:
        await _provider(handler).generate_json("x")
    assert info.value.daily is True


async def test_429_with_long_wait_is_not_inferred_as_daily():
    """A long retry-after is passed through for the pool to judge; it is not
    a daily cap. Inferring one from the wait's size cooled a token-bucket
    stall for an hour in a live run."""
    handler, _ = _capture(
        httpx.Response(
            429,
            headers={"retry-after": "7200", "x-ratelimit-remaining-requests": "500"},
            text="slow down",
        )
    )
    with pytest.raises(ProviderExhaustedError) as info:
        await _provider(handler).generate_json("x")
    assert info.value.daily is False
    assert info.value.retry_after == 7200.0


async def test_429_message_carries_remaining_budgets_for_diagnosis():
    handler, _ = _capture(
        httpx.Response(
            429,
            headers={
                "retry-after": "12",
                "x-ratelimit-remaining-requests": "900",
                "x-ratelimit-remaining-tokens": "310",
            },
            json={"error": {"message": "Rate limit reached"}},
        )
    )
    with pytest.raises(ProviderExhaustedError) as info:
        await _provider(handler).generate_json("x")
    assert "requests=900.0" in str(info.value)
    assert "tokens=310.0" in str(info.value)
    assert "retry-after=12.0" in str(info.value)


async def test_5xx_is_retried_then_unavailable():
    handler, seen = _capture(httpx.Response(503, text="down"))
    with pytest.raises(ProviderUnavailableError):
        await _provider(handler, retry_attempts=3).generate_json("x")
    assert len(seen) == 3


async def test_transport_error_is_retried_then_unavailable():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ProviderUnavailableError):
        await _provider(handler, retry_attempts=2).generate_json("x")
    assert calls == 2


async def test_400_is_call_specific_not_failover():
    handler, seen = _capture(httpx.Response(400, text="bad request"))
    with pytest.raises(ProviderError) as info:
        await _provider(handler).generate_json("x")
    assert not isinstance(info.value, ProviderExhaustedError | ProviderUnavailableError)
    assert len(seen) == 1


async def test_unexpected_shape_is_provider_error():
    handler, _ = _capture(httpx.Response(200, json={"choices": []}))
    with pytest.raises(ProviderError, match="unexpected response shape"):
        await _provider(handler).generate_json("x")


async def test_empty_completion_is_provider_error():
    handler, _ = _capture(httpx.Response(200, json=_completion("   ")))
    with pytest.raises(ProviderError, match="empty completion"):
        await _provider(handler).generate_json("x")


async def test_non_object_json_is_provider_error():
    """The contract is a JSON object; a top-level list must not leak through."""
    handler, _ = _capture(httpx.Response(200, json=_completion('[{"a": 1}]')))
    with pytest.raises(ProviderError, match="not a JSON object"):
        await _provider(handler).generate_json("x")


async def test_close_closes_client():
    handler, _ = _capture(httpx.Response(200, json=_completion("{}")))
    p = _provider(handler)
    await p.close()
    assert p._client.is_closed
