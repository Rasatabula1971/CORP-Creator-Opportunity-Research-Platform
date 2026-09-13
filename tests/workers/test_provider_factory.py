"""Unit tests for provider selection from settings."""

import pytest

from corp.config import Settings
from corp.workers.providers.factory import ProviderConfigError, build_provider
from corp.workers.providers.fair import FairProvider
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
