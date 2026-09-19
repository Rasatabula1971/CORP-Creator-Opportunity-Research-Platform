"""Unit tests for cluster naming — the LLM may name, and only name what the evidence supports."""

import pytest

from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.niche_naming import (
    NICHE_NAME_SCHEMA,
    check_grounding,
    name_cluster,
)
from corp.workers.providers.registry import LLMProvider

TEXTS = [
    "Espresso machine leaking from group head - how to fix",
    "Why my home espresso shots taste sour (grind size explained)",
    "Best budget espresso grinders for home baristas 2026",
]


class FakeProvider(LLMProvider):
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    @property
    def model_name(self) -> str:
        return "fake"

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        if self._error:
            raise self._error
        return self._response


def _answer(**overrides):
    base = {
        "name": "Home Espresso",
        "description": "People fixing and tuning home espresso setups.",
        "is_broad_domain": False,
        "confidence": 0.9,
        "evidence_terms": ["espresso machine", "grind size", "home baristas"],
    }
    return base | overrides


# ── grounding ─────────────────────────────────────────────────────────


def test_check_grounding_is_case_and_space_insensitive():
    assert check_grounding(["ESPRESSO  machine", "Grind size"], TEXTS) == []


def test_check_grounding_reports_missing_terms():
    assert check_grounding(["espresso machine", "latte art", "ok"], TEXTS) == ["latte art", "ok"]


def test_check_grounding_does_not_reject_a_genuinely_present_short_term():
    """A short term that's actually cited in the evidence (e.g. "to" in "how
    to fix") must not be discarded just for being short — that used to
    silently fail an otherwise well-grounded naming result."""
    assert check_grounding(["to"], TEXTS) == []


def test_check_grounding_rejects_short_term_matching_only_as_a_fragment():
    """A short needle must match a whole word, not a substring of a longer,
    unrelated one (e.g. "to" inside "shots")."""
    assert check_grounding(["hot"], ["the shots taste sour"]) == ["hot"]


# ── the call ──────────────────────────────────────────────────────────


async def test_grounded_answer_is_accepted():
    provider = FakeProvider(_answer())
    named = await name_cluster(provider, TEXTS, platform="youtube")
    assert named.grounded is True
    assert named.name == "Home Espresso"
    assert named.evidence_terms == ["espresso machine", "grind size", "home baristas"]
    assert named.is_broad_domain is False
    assert named.confidence == 0.9
    call = provider.calls[0]
    assert call["schema"] is NICHE_NAME_SCHEMA
    assert "Platform: youtube" in call["prompt"]
    assert "3 of 3 in the cluster" in call["prompt"]
    for t in TEXTS:
        assert t in call["prompt"]


async def test_ungrounded_term_rejects_the_name():
    provider = FakeProvider(_answer(evidence_terms=["espresso machine", "latte art"]))
    named = await name_cluster(provider, TEXTS)
    assert named.grounded is False
    assert named.ungrounded_terms == ["latte art"]
    assert named.name == "Home Espresso"  # still reported, for the audit trail


async def test_no_terms_is_ungrounded():
    named = await name_cluster(FakeProvider(_answer(evidence_terms=[])), TEXTS)
    assert named.grounded is False


async def test_empty_name_is_ungrounded():
    named = await name_cluster(FakeProvider(_answer(name="  ")), TEXTS)
    assert named.grounded is False


async def test_broad_domain_flag_and_confidence_clamped():
    named = await name_cluster(
        FakeProvider(_answer(name="Coffee", is_broad_domain=True, confidence=7)), TEXTS
    )
    assert named.is_broad_domain is True
    assert named.confidence == 1.0


async def test_non_dict_answer_is_ungrounded_not_an_error():
    named = await name_cluster(FakeProvider(["not", "a", "dict"]), TEXTS)
    assert named.grounded is False
    assert named.name == ""


async def test_provider_failure_is_llm_call_error():
    with pytest.raises(LLMCallError):
        await name_cluster(FakeProvider(error=RuntimeError("down")), TEXTS)


async def test_only_twelve_texts_are_shown_but_total_is_stated():
    provider = FakeProvider(_answer(evidence_terms=["espresso"]))
    many = [f"espresso video number {i}" for i in range(20)]
    await name_cluster(provider, many)
    prompt = provider.calls[0]["prompt"]
    assert "12 of 20 in the cluster" in prompt
    assert "espresso video number 11" in prompt
    assert "espresso video number 12" not in prompt
