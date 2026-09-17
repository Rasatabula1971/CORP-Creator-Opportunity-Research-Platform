"""Unit tests for the LLM provider registry."""

from collections.abc import Callable

import pytest

from corp.workers.providers.errors import (
    ProviderError,
    ProviderExhaustedError,
    ProviderUnavailableError,
)
from corp.workers.providers.registry import (
    GeminiProvider,
    LLMProvider,
    _response_hash,
    classify_quota_error,
)


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


# ── Gemini quota classification (offline: genai stubbed) ─────────────


class _FakeClient:
    """Stands in for genai.Client; scripts client.aio.models.generate_content."""

    def __init__(self, outcomes: list):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.aio = self
        self.models = self

    async def generate_content(self, *, model, contents, config):
        self.calls += 1
        item = self.outcomes.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _Response:
    def __init__(self, text: str | None, finish_reason: object = None) -> None:
        self.text = text
        self.candidates = (
            [type("Candidate", (), {"finish_reason": finish_reason})()]
            if finish_reason is not None
            else []
        )


def _client_error(code: int, message: str):
    from google.genai import errors as genai_errors

    body = {"error": {"message": message, "status": "RESOURCE_EXHAUSTED"}}
    return genai_errors.ClientError(code, body)


def _server_error(code: int, message: str):
    from google.genai import errors as genai_errors

    body = {"error": {"message": message, "status": "UNAVAILABLE"}}
    return genai_errors.ServerError(code, body)


@pytest.fixture
def gemini(monkeypatch):
    """A GeminiProvider whose client is a scripted fake; retries are near-instant."""
    fakes: list[_FakeClient] = []

    def make(outcomes):
        fake = _FakeClient(outcomes)
        fakes.append(fake)
        monkeypatch.setattr(
            "corp.workers.providers.registry.genai.Client", lambda *a, **kw: fake
        )
        return (
            GeminiProvider(
                api_key="k",
                model="gemini-3.6-flash",
                retry_attempts=3,
                retry_wait_min=0.001,
                retry_wait_max=0.001,
            ),
            fake,
        )

    return make


_Gemini = Callable[[list[object]], tuple[GeminiProvider, _FakeClient]]

DAILY_429 = (
    "429 You exceeded your current quota. * Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20 "
    "Please retry in 40.087555169s. quota_id: "
    "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
)
MINUTE_429 = (
    "429 Resource has been exhausted. quota_id: GenerateRequestsPerMinutePerProjectPerModel "
    "Please retry in 8.3s."
)


async def test_success_parses_json(gemini):
    provider, fake = gemini([_Response('{"ok": 1}')])
    assert await provider.generate_json("p") == {"ok": 1}
    assert fake.calls == 1


@pytest.mark.parametrize("text", [None, "", "  \n"])
async def test_empty_completion_is_a_provider_error(gemini: _Gemini, text: str | None) -> None:
    # response.text is None on a safety block, MAX_TOKENS on a thought-only
    # part, or no candidates. That must be a ProviderError the caller can
    # count against the item — not a TypeError out of json.loads(None), and
    # not a pool signal (exhausted/unavailable) either.
    from enum import Enum

    class FinishReason(Enum):
        MAX_TOKENS = "MAX_TOKENS"

    provider, fake = gemini([_Response(text, finish_reason=FinishReason.MAX_TOKENS)])
    with pytest.raises(ProviderError) as info:
        await provider.generate_json("p")
    assert not isinstance(info.value, ProviderExhaustedError | ProviderUnavailableError)
    assert info.value.provider == "gemini-3.6-flash"
    assert "empty completion" in str(info.value)
    assert "finish_reason=MAX_TOKENS" in str(info.value)
    assert fake.calls == 1


async def test_empty_completion_without_candidates_names_unknown_reason(gemini: _Gemini) -> None:
    provider, _ = gemini([_Response(None)])
    with pytest.raises(ProviderError, match=r"finish_reason=None"):
        await provider.generate_json("p")


async def test_daily_cap_is_exhausted_immediately_no_retry(gemini):
    provider, fake = gemini([_client_error(429, DAILY_429)])
    with pytest.raises(ProviderExhaustedError) as info:
        await provider.generate_json("p")
    assert info.value.daily is True
    assert info.value.retry_after is None  # the 40s hint is meaningless on a daily cap
    assert info.value.provider == "gemini-3.6-flash"
    assert fake.calls == 1


async def test_per_minute_limit_carries_retry_after(gemini):
    provider, fake = gemini([_client_error(429, MINUTE_429)])
    with pytest.raises(ProviderExhaustedError) as info:
        await provider.generate_json("p")
    assert info.value.daily is False
    assert info.value.retry_after == 8.3
    assert fake.calls == 1


async def test_transient_is_retried_then_unavailable(gemini):
    provider, fake = gemini([_server_error(503, "unavailable")] * 3)
    with pytest.raises(ProviderUnavailableError):
        await provider.generate_json("p")
    assert fake.calls == 3


async def test_transient_then_success_recovers(gemini):
    provider, fake = gemini([_server_error(504, "deadline"), _Response('{"ok": 2}')])
    assert await provider.generate_json("p") == {"ok": 2}
    assert fake.calls == 2


async def test_non_quota_client_error_passes_through(gemini):
    # A 400 (bad request) is neither transient nor a quota signal: no retry,
    # no ProviderExhaustedError — the original error surfaces.
    from google.genai import errors as genai_errors

    provider, fake = gemini([_client_error(400, "bad request")])
    with pytest.raises(genai_errors.ClientError):
        await provider.generate_json("p")
    assert fake.calls == 1


def test_classify_quota_error_daily_vs_minute():
    daily = classify_quota_error("m", Exception(DAILY_429))
    minute = classify_quota_error("m", Exception(MINUTE_429))
    assert (daily.daily, daily.retry_after) == (True, None)
    assert (minute.daily, minute.retry_after) == (False, 8.3)


async def test_concrete_provider_satisfies_interface():
    class TestProvider(LLMProvider):
        @property
        def model_name(self) -> str:
            return "test-v1"

        async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
            return {"result": True}

    p = TestProvider()
    assert p.model_name == "test-v1"
    result = await p.generate_json("hello")
    assert result == {"result": True}
