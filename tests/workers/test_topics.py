"""Unit tests for topic classification — LLM calls mocked."""

from corp.workers.intelligence.topics import TOPIC_PROMPT_VERSION, classify_topics
from corp.workers.providers.registry import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, response: dict | None = None) -> None:
        self._response = response or {
            "topics": [
                {"name": "Tech Reviews", "confidence": 0.95, "evidence_count": 8},
                {"name": "Smartphones", "confidence": 0.85, "evidence_count": 6},
                {"name": "Camera Comparisons", "confidence": 0.7, "evidence_count": 3},
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
        raise RuntimeError("API down")


async def test_classify_topics_basic():
    provider = FakeProvider()
    content = [
        {"title": "iPhone 15 Review", "description": "Full review"},
        {"title": "Galaxy S24 vs iPhone 15", "description": "Camera test"},
    ]
    topics = await classify_topics(provider, content)
    assert len(topics) == 3
    assert topics[0]["name"] == "Tech Reviews"
    assert topics[0]["confidence"] == 0.95
    assert topics[0]["evidence_count"] == 8


async def test_classify_topics_empty_content():
    provider = FakeProvider({"topics": []})
    topics = await classify_topics(provider, [])
    assert topics == []


async def test_classify_topics_malformed_response():
    provider = FakeProvider({"topics": [{"no_name": True}, "junk"]})
    topics = await classify_topics(provider, [{"title": "X"}])
    assert topics == []


async def test_classify_topics_provider_failure():
    provider = FailingProvider()
    topics = await classify_topics(provider, [{"title": "X"}])
    assert topics == []


async def test_classify_topics_clamps_confidence():
    provider = FakeProvider({"topics": [{"name": "AI", "confidence": 2.0, "evidence_count": 1}]})
    topics = await classify_topics(provider, [{"title": "X"}])
    assert topics[0]["confidence"] == 1.0


async def test_classify_topics_name_truncation():
    long_name = "A" * 200
    provider = FakeProvider({"topics": [{"name": long_name, "confidence": 0.5}]})
    topics = await classify_topics(provider, [{"title": "X"}])
    assert len(topics[0]["name"]) == 100


async def test_topic_prompt_version():
    assert TOPIC_PROMPT_VERSION == "topics_v1"
