"""Unit tests for the LLM provider registry."""

import pytest

from corp.workers.providers.errors import ProviderExhaustedError, ProviderUnavailableError
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


class _FakeModel:
    def __init__(self, outcomes: list):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate_content_async(self, prompt, generation_config=None):
        self.calls += 1
        item = self.outcomes.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _Response:
    def __init__(self, text: str):
        self.text = text


@pytest.fixture
def gemini(monkeypatch):
    """A GeminiProvider whose model is a scripted fake; retries are near-instant."""
    fakes: list[_FakeModel] = []

    def make(outcomes):
        fake = _FakeModel(outcomes)
        fakes.append(fake)
        monkeypatch.setattr("corp.workers.providers.registry.genai.configure", lambda **kw: None)
        monkeypatch.setattr(
            "corp.workers.providers.registry.genai.GenerativeModel", lambda *a, **kw: fake
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


async def test_daily_cap_is_exhausted_immediately_no_retry(gemini):
    from google.api_core.exceptions import ResourceExhausted

    provider, fake = gemini([ResourceExhausted(DAILY_429)])
    with pytest.raises(ProviderExhaustedError) as info:
        await provider.generate_json("p")
    assert info.value.daily is True
    assert info.value.retry_after is None  # the 40s hint is meaningless on a daily cap
    assert info.value.provider == "gemini-3.6-flash"
    assert fake.calls == 1


async def test_per_minute_limit_carries_retry_after(gemini):
    from google.api_core.exceptions import ResourceExhausted

    provider, fake = gemini([ResourceExhausted(MINUTE_429)])
    with pytest.raises(ProviderExhaustedError) as info:
        await provider.generate_json("p")
    assert info.value.daily is False
    assert info.value.retry_after == 8.3
    assert fake.calls == 1


async def test_transient_is_retried_then_unavailable(gemini):
    from google.api_core.exceptions import ServiceUnavailable

    provider, fake = gemini([ServiceUnavailable("503")] * 3)
    with pytest.raises(ProviderUnavailableError):
        await provider.generate_json("p")
    assert fake.calls == 3


async def test_transient_then_success_recovers(gemini):
    from google.api_core.exceptions import DeadlineExceeded

    provider, fake = gemini([DeadlineExceeded("504"), _Response('{"ok": 2}')])
    assert await provider.generate_json("p") == {"ok": 2}
    assert fake.calls == 2


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
