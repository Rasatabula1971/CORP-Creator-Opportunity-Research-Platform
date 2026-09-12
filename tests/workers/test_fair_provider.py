"""Unit tests for the FAIR provider adapter."""

import json

import httpx
import pytest

from corp.workers.providers.fair import FairProvider, FairProviderError
from corp.workers.providers.registry import LLMProvider


def _mock_transport(status_code: int, body: dict):
    """Return an httpx transport that always returns the given response."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handler)


def _fair_response(
    output: str | None = None,
    status: str = "ACCEPTED",
    reason_code: str = "QUALITY_THRESHOLD_MET",
    provider_id: str = "groq",
    model_id: str = "llama-3-8b",
) -> dict:
    return {
        "request_id": "test-req-1",
        "status": status,
        "reason_code": reason_code,
        "output": output,
        "provider_id": provider_id,
        "model_id": model_id,
        "attempts": [],
        "minimum_required": 50.0,
    }


@pytest.fixture
def accepted_provider():
    output = json.dumps({"observations": [{"text": "test", "category": "problem"}]})
    transport = _mock_transport(200, _fair_response(output=output))
    provider = FairProvider(
        base_url="http://fair-test:8000",
        client_id="corp-test",
        api_key="test-key",
    )
    provider._client = httpx.AsyncClient(
        base_url="http://fair-test:8000",
        transport=transport,
    )
    return provider


@pytest.fixture
def escalated_provider():
    transport = _mock_transport(
        200,
        _fair_response(
            status="ESCALATION_REQUIRED",
            reason_code="ALL_FREE_MODELS_FAILED_QUALITY",
        ),
    )
    provider = FairProvider(
        base_url="http://fair-test:8000",
        client_id="corp-test",
        api_key="test-key",
    )
    provider._client = httpx.AsyncClient(
        base_url="http://fair-test:8000",
        transport=transport,
    )
    return provider


@pytest.fixture
def failed_provider():
    transport = _mock_transport(
        200,
        _fair_response(
            status="FAILED",
            reason_code="SYSTEM_STOPPED",
        ),
    )
    provider = FairProvider(
        base_url="http://fair-test:8000",
        client_id="corp-test",
        api_key="test-key",
    )
    provider._client = httpx.AsyncClient(
        base_url="http://fair-test:8000",
        transport=transport,
    )
    return provider


async def test_implements_llm_provider():
    provider = FairProvider(
        base_url="http://localhost:8000",
        client_id="test",
        api_key="key",
    )
    assert isinstance(provider, LLMProvider)


async def test_model_name():
    provider = FairProvider(
        base_url="http://localhost:8000",
        client_id="test",
        api_key="key",
    )
    assert provider.model_name == "fair-router"


async def test_generate_json_accepted(accepted_provider):
    result = await accepted_provider.generate_json("Extract problems from this comment")
    assert result == {"observations": [{"text": "test", "category": "problem"}]}
    await accepted_provider.close()


async def test_generate_json_with_system_prompt(accepted_provider):
    """System prompt is prepended to the task."""
    captured = []
    original_transport = accepted_provider._client._transport

    async def capturing_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return await original_transport.handle_async_request(request)

    accepted_provider._client._transport = httpx.MockTransport(capturing_handler)

    await accepted_provider.generate_json("user prompt", system="system instructions")
    assert len(captured) == 1
    assert captured[0]["task"] == "system instructions\n\nuser prompt"
    assert captured[0]["client_id"] == "corp-test"
    await accepted_provider.close()


async def test_generate_json_escalation_raises(escalated_provider):
    with pytest.raises(FairProviderError) as exc_info:
        await escalated_provider.generate_json("test prompt")
    assert exc_info.value.status == "ESCALATION_REQUIRED"
    assert exc_info.value.reason_code == "ALL_FREE_MODELS_FAILED_QUALITY"
    await escalated_provider.close()


async def test_generate_json_failed_raises(failed_provider):
    with pytest.raises(FairProviderError) as exc_info:
        await failed_provider.generate_json("test prompt")
    assert exc_info.value.status == "FAILED"
    assert exc_info.value.reason_code == "SYSTEM_STOPPED"
    await failed_provider.close()


async def test_generate_json_http_error():
    transport = _mock_transport(500, {"detail": "Internal Server Error"})
    provider = FairProvider(
        base_url="http://fair-test:8000",
        client_id="corp-test",
        api_key="test-key",
    )
    provider._client = httpx.AsyncClient(
        base_url="http://fair-test:8000",
        transport=transport,
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.generate_json("test")
    await provider.close()


async def test_generate_json_invalid_json_output():
    """FAIR returns ACCEPTED but output is not valid JSON."""
    transport = _mock_transport(
        200,
        _fair_response(output="not json at all"),
    )
    provider = FairProvider(
        base_url="http://fair-test:8000",
        client_id="corp-test",
        api_key="test-key",
    )
    provider._client = httpx.AsyncClient(
        base_url="http://fair-test:8000",
        transport=transport,
    )
    with pytest.raises(json.JSONDecodeError):
        await provider.generate_json("test")
    await provider.close()


async def test_accepted_but_null_output_raises():
    """ACCEPTED status but null output should raise."""
    transport = _mock_transport(200, _fair_response(status="ACCEPTED", output=None))
    provider = FairProvider(
        base_url="http://fair-test:8000",
        client_id="corp-test",
        api_key="test-key",
    )
    provider._client = httpx.AsyncClient(
        base_url="http://fair-test:8000",
        transport=transport,
    )
    with pytest.raises(FairProviderError):
        await provider.generate_json("test")
    await provider.close()


async def test_request_sends_correct_payload():
    """Verify the payload sent to FAIR's /v1/solve."""
    captured = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        output = json.dumps({"result": True})
        return httpx.Response(200, json=_fair_response(output=output))

    provider = FairProvider(
        base_url="http://fair-test:8000",
        client_id="my-corp-client",
        api_key="secret",
    )
    provider._client = httpx.AsyncClient(
        base_url="http://fair-test:8000",
        transport=httpx.MockTransport(handler),
    )

    await provider.generate_json("hello world")
    assert len(captured) == 1
    assert captured[0] == {
        "client_id": "my-corp-client",
        "task": "hello world",
        "quality_level": "standard",
        "priority": "P2",
    }
    await provider.close()


async def test_close_idempotent():
    provider = FairProvider(
        base_url="http://localhost:8000",
        client_id="test",
        api_key="key",
    )
    await provider.close()
    await provider.close()
