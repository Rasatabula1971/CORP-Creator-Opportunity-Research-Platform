"""Unit tests for commercial intent classification — LLM calls mocked."""

import pytest

from corp.core.models.intent import SignalLevel
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.intent import (
    INTENT_PROMPT_VERSION,
    IntentClassification,
    _reconcile,
    classify_cluster_intent,
)
from corp.workers.providers.registry import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, response: dict | None = None) -> None:
        self._response = response or {
            "signal_level": "strong",
            "rationale": "Multiple comments ask about purchasing",
            "confidence": 0.85,
            "key_indicators": ["where can I buy", "pricing"],
        }

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
        return self._response


class FailingProvider(LLMProvider):
    @property
    def model_name(self) -> str:
        return "failing"

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
        raise RuntimeError("API down")


async def test_classify_cluster_intent_basic():
    provider = FakeProvider()
    result = await classify_cluster_intent(
        provider=provider,
        label="Battery Issues",
        description="Users report battery problems",
        frequency=10,
        evidence_strength=0.8,
        representative_texts=["where can I buy a replacement battery?"],
        rules_path=None,
    )

    assert isinstance(result, IntentClassification)
    assert result.signal_level in list(SignalLevel)
    assert result.confidence > 0
    assert result.rationale


async def test_classify_cluster_intent_validation_level():
    provider = FakeProvider({
        "signal_level": "validation",
        "rationale": "Users discussing competitors",
        "confidence": 0.9,
        "key_indicators": ["I already purchased"],
    })
    result = await classify_cluster_intent(
        provider=provider,
        label="Product Comparison",
        description="Comparing products",
        frequency=5,
        evidence_strength=0.6,
        representative_texts=["I already purchased the competitor's version"],
        rules_path=None,
    )

    assert result.signal_level == SignalLevel.VALIDATION


async def test_classify_cluster_intent_llm_failure_raises():
    """LLM failure propagates so the pipeline can count it, not silently weak."""
    provider = FailingProvider()
    with pytest.raises(LLMCallError, match="intent:"):
        await classify_cluster_intent(
            provider=provider,
            label="Test",
            description="Test",
            frequency=1,
            evidence_strength=0.1,
            representative_texts=["something annoying happened"],
            rules_path=None,
        )


async def test_classify_cluster_intent_invalid_level():
    provider = FakeProvider({
        "signal_level": "invalid_level",
        "rationale": "bad",
        "confidence": 0.5,
        "key_indicators": [],
    })
    result = await classify_cluster_intent(
        provider=provider,
        label="Test",
        description="Test",
        frequency=1,
        evidence_strength=0.1,
        representative_texts=["generic text"],
        rules_path=None,
    )

    assert result.signal_level == SignalLevel.WEAK


async def test_reconcile_llm_higher():
    assert _reconcile(SignalLevel.WEAK, SignalLevel.STRONG) == SignalLevel.STRONG


async def test_reconcile_rules_higher():
    assert _reconcile(SignalLevel.STRONG, SignalLevel.WEAK) == SignalLevel.STRONG


async def test_reconcile_equal():
    assert _reconcile(SignalLevel.MODERATE, SignalLevel.MODERATE) == SignalLevel.MODERATE


async def test_reconcile_validation_wins():
    assert _reconcile(SignalLevel.VALIDATION, SignalLevel.MODERATE) == SignalLevel.VALIDATION
    assert _reconcile(SignalLevel.MODERATE, SignalLevel.VALIDATION) == SignalLevel.VALIDATION


async def test_prompt_version_constant():
    assert INTENT_PROMPT_VERSION == "intent_v1"


async def test_classify_confidence_clamping():
    provider = FakeProvider({
        "signal_level": "moderate",
        "rationale": "test",
        "confidence": 5.0,
        "key_indicators": [],
    })
    result = await classify_cluster_intent(
        provider=provider,
        label="Test",
        description="",
        frequency=1,
        evidence_strength=0.1,
        representative_texts=["struggling with this"],
        rules_path=None,
    )
    assert result.confidence == 1.0


async def test_classify_key_indicators_truncated():
    provider = FakeProvider({
        "signal_level": "strong",
        "rationale": "test",
        "confidence": 0.8,
        "key_indicators": [f"indicator_{i}" for i in range(20)],
    })
    result = await classify_cluster_intent(
        provider=provider,
        label="Test",
        description="",
        frequency=1,
        evidence_strength=0.5,
        representative_texts=["where can I buy this?"],
        rules_path=None,
    )
    assert len(result.key_indicators) <= 10
