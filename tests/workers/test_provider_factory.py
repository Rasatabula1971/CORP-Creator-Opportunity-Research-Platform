"""Unit tests for provider selection from settings."""

import pytest

from corp.config import Settings
from corp.workers.providers.factory import ProviderConfigError, build_provider
from corp.workers.providers.fair import FairProvider
from corp.workers.providers.groq import GroqProvider
from corp.workers.providers.pool import PooledProvider
from corp.workers.providers.registry import GeminiProvider


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def stub_genai(monkeypatch):
    """Keep GeminiProvider construction offline."""
    monkeypatch.setattr("corp.workers.providers.registry.genai.configure", lambda **kw: None)
    monkeypatch.setattr(
        "corp.workers.providers.registry.genai.GenerativeModel", lambda *a, **kw: object()
    )


def test_auto_prefers_fair_when_url_set():
    cfg = _settings(fair_url="http://fair:8080", fair_api_key="k", gemini_api_key="g")
    provider = build_provider(cfg)
    assert isinstance(provider, FairProvider)
    assert provider.model_name == "fair-router"


def test_auto_falls_back_to_gemini(stub_genai):
    cfg = _settings(fair_url="", gemini_api_key="g")
    assert isinstance(build_provider(cfg), GeminiProvider)


def test_auto_with_nothing_configured_raises():
    with pytest.raises(ProviderConfigError):
        build_provider(_settings(fair_url="", gemini_api_key=""))


def test_explicit_fair_without_url_raises():
    with pytest.raises(ProviderConfigError):
        build_provider(_settings(llm_provider="fair", fair_url="", gemini_api_key="g"))


def test_explicit_gemini_ignores_fair(stub_genai):
    cfg = _settings(llm_provider="gemini", fair_url="http://fair:8080", gemini_api_key="g")
    assert isinstance(build_provider(cfg), GeminiProvider)


def test_unknown_choice_raises():
    with pytest.raises(ProviderConfigError):
        build_provider(_settings(llm_provider="openai"))


def test_auto_pools_gemini_and_groq_in_configured_order(stub_genai):
    cfg = _settings(fair_url="", gemini_api_key="g", groq_api_key="q")
    provider = build_provider(cfg)
    assert isinstance(provider, PooledProvider)
    names = [p.model_name for p in provider.available()]
    assert names == ["gemini-2.0-flash", "groq/openai/gpt-oss-20b"]


def test_provider_order_is_honoured(stub_genai):
    cfg = _settings(
        fair_url="", gemini_api_key="g", groq_api_key="q", llm_provider_order="groq, gemini"
    )
    names = [p.model_name for p in build_provider(cfg).available()]
    assert names == ["groq/openai/gpt-oss-20b", "gemini-2.0-flash"]


def test_auto_with_only_groq_returns_bare_groq():
    provider = build_provider(_settings(fair_url="", gemini_api_key="", groq_api_key="q"))
    assert isinstance(provider, GroqProvider)


def test_explicit_groq_ignores_gemini(stub_genai):
    cfg = _settings(llm_provider="groq", gemini_api_key="g", groq_api_key="q")
    assert isinstance(build_provider(cfg), GroqProvider)


def test_explicit_groq_without_key_raises():
    with pytest.raises(ProviderConfigError):
        build_provider(_settings(llm_provider="groq", groq_api_key=""))


def test_explicit_pool_with_one_key_still_pools():
    provider = build_provider(_settings(llm_provider="pool", groq_api_key="q"))
    assert isinstance(provider, PooledProvider)


def test_explicit_pool_with_no_keys_raises():
    with pytest.raises(ProviderConfigError):
        build_provider(_settings(llm_provider="pool", gemini_api_key="", groq_api_key=""))


def test_unknown_pool_member_raises():
    with pytest.raises(ProviderConfigError, match="LLM_PROVIDER_ORDER"):
        build_provider(_settings(fair_url="", groq_api_key="q", llm_provider_order="groq,openai"))


def test_groq_settings_are_forwarded():
    cfg = _settings(
        llm_provider="groq",
        groq_api_key="q",
        groq_model="m",
        groq_timeout_seconds=7.5,
        groq_max_output_tokens=1234,
        groq_reasoning_effort="medium",
    )
    provider = build_provider(cfg)
    assert isinstance(provider, GroqProvider)
    assert provider.model_name == "groq/m"
    assert provider._client.timeout.read == 7.5
    assert provider._max_output_tokens == 1234
    assert provider._reasoning_effort == "medium"


def test_groq_empty_reasoning_effort_means_none():
    cfg = _settings(llm_provider="groq", groq_api_key="q", groq_reasoning_effort="")
    provider = build_provider(cfg)
    assert isinstance(provider, GroqProvider)
    assert provider._reasoning_effort is None


def test_cooldown_and_max_wait_settings_reach_pool(stub_genai):
    cfg = _settings(
        fair_url="",
        gemini_api_key="g",
        groq_api_key="q",
        llm_cooldown_seconds=42,
        llm_max_wait_seconds=7,
    )
    pool = build_provider(cfg)
    assert pool._cooldown == 42
    assert pool._max_wait == 7


def test_fair_settings_are_forwarded():
    cfg = _settings(
        fair_url="http://fair:8080/",
        fair_client_id="corp-prod",
        fair_quality_level="high",
        fair_priority="P1",
        fair_timeout_seconds=12.5,
    )
    provider = build_provider(cfg)
    assert isinstance(provider, FairProvider)
    assert provider._base_url == "http://fair:8080"
    assert provider._client_id == "corp-prod"
    assert provider._quality_level == "high"
    assert provider._priority == "P1"
    assert provider._timeout == 12.5
