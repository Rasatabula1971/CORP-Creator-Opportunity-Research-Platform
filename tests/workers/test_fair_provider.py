"""Unit tests for the in-process FAIR provider adapter — no FAIR package needed."""

import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from corp.workers.providers.errors import (
    ProviderError,
    ProviderExhaustedError,
    ProviderUnavailableError,
)
from corp.workers.providers.fair import FairProvider, PingResult, _strip_code_fence
from corp.workers.providers.registry import LLMProvider

# ── a fake FAIR router with the surface the adapter uses ──────────────


@dataclass
class Attempt:
    provider_id: str
    model_id: str
    disposition: str
    error_type: str | None = None


@dataclass
class Solve:
    status: str = "ACCEPTED"
    reason_code: str = "QUALITY_THRESHOLD_MET"
    output: str | None = None
    provider_id: str | None = "groq"
    model_id: str | None = "openai/gpt-oss-20b"
    attempts: list = field(default_factory=list)
    best_quality_score: float | None = 85.0
    minimum_required: float = 82.0
    verification_state: str = "STRUCTURE_VALIDATED"
    cache_hit: bool = False


class FakeFair:
    def __init__(self, *responses: Solve | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.closed = False
        self.skipped: dict[str, str] = {}

    async def solve(self, task, **kwargs):
        self.calls.append({"task": task, **kwargs})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def providers(self):
        return [
            {"provider_id": "google_gemini_api", "models": ["gemini-3.6-flash"]},
            {"provider_id": "groq", "models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]},
        ]

    async def close(self):
        self.closed = True


SCHEMA = {"type": "object", "required": ["observations"]}


def _accepted(payload: dict, **kw) -> Solve:
    return Solve(output=json.dumps(payload), **kw)


# ── contract ──────────────────────────────────────────────────────────


def test_is_an_llm_provider():
    assert issubclass(FairProvider, LLMProvider)


def test_model_name_before_any_call_is_router_label():
    assert FairProvider(FakeFair()).model_name == "fair-router"


def test_labels_are_vendor_canonical_so_pool_and_fair_work_share_a_family():
    """gpt-oss-20b via FAIR is the same model the bare GroqProvider records as
    ``groq/openai/gpt-oss-20b``; other vendors get ``<provider>/<model>``."""
    from corp.workers.providers.fair import _model_label

    assert _model_label("google_gemini_api", "gemini-3.6-flash") == "gemini-3.6-flash"
    assert _model_label("groq", "openai/gpt-oss-20b") == "groq/openai/gpt-oss-20b"
    assert _model_label("mistral", "ministral-8b-latest") == "mistral/ministral-8b-latest"
    assert _model_label(None, None) == "unknown/unknown"


def test_member_names_cover_every_routable_model():
    names = FairProvider(FakeFair()).member_names()
    assert names == [
        "fair-router",
        "gemini-3.6-flash",
        "groq/openai/gpt-oss-20b",
        "groq/openai/gpt-oss-120b",
    ]


# ── the call ──────────────────────────────────────────────────────────


async def test_accepted_answer_is_parsed_and_attributed():
    fair = FakeFair(_accepted({"observations": [{"text": "x"}]}))
    provider = FairProvider(fair, client_id="corp-test", quality_level="commodity", priority="P1")
    out = await provider.generate_json("prompt", system="sys", schema=SCHEMA)
    assert out == {"observations": [{"text": "x"}]}
    assert provider.model_name == "groq/openai/gpt-oss-20b"
    assert provider.models_used() == {"groq/openai/gpt-oss-20b"}
    call = fair.calls[0]
    assert call["task"] == "sys\n\nprompt"
    assert call["expected_schema"] is SCHEMA
    assert call["task_type"] == "extraction"
    assert call["quality_level"] == "commodity"
    assert call["client_id"] == "corp-test"
    assert call["priority"] == "P1"
    assert call["max_output_tokens"] == 2048


async def test_no_system_prompt_sends_prompt_alone():
    fair = FakeFair(_accepted({"a": 1}))
    await FairProvider(fair).generate_json("just this", schema=SCHEMA)
    assert fair.calls[0]["task"] == "just this"


async def test_fenced_json_is_unwrapped():
    fair = FakeFair(Solve(output='```json\n{"observations": []}\n```'))
    assert await FairProvider(fair).generate_json("p", schema=SCHEMA) == {"observations": []}


def test_strip_code_fence_leaves_plain_text_alone():
    assert _strip_code_fence('{"a": 1}') == '{"a": 1}'
    assert _strip_code_fence("```\n{}\n```") == "{}"


async def test_models_used_accumulates_across_members():
    fair = FakeFair(
        _accepted({"a": 1}, provider_id="google_gemini_api", model_id="gemini-3.6-flash"),
        _accepted({"a": 2}, provider_id="groq", model_id="openai/gpt-oss-20b"),
    )
    provider = FairProvider(fair)
    await provider.generate_json("p", schema=SCHEMA)
    assert provider.model_name == "gemini-3.6-flash"
    await provider.generate_json("p", schema=SCHEMA)
    assert provider.model_name == "groq/openai/gpt-oss-20b"
    assert provider.models_used() == {
        "gemini-3.6-flash",
        "groq/openai/gpt-oss-20b",
    }


async def test_missing_schema_still_calls_but_warns(caplog):
    fair = FakeFair(_accepted({"a": 1}))
    with caplog.at_level("WARNING"):
        await FairProvider(fair).generate_json("p")
    assert fair.calls[0]["expected_schema"] is None
    assert "without an expected schema" in caplog.text


async def test_close_closes_router():
    fair = FakeFair()
    await FairProvider(fair).close()
    assert fair.closed


# ── rejections: accepted-but-bad output ───────────────────────────────


async def test_accepted_non_object_json_is_a_provider_error():
    fair = FakeFair(Solve(output="[1, 2, 3]"))
    with pytest.raises(ProviderError, match="not a JSON object"):
        await FairProvider(fair).generate_json("p", schema=SCHEMA)


async def test_accepted_unparseable_output_is_a_provider_error():
    fair = FakeFair(Solve(output="not json at all"))
    with pytest.raises(ProviderError, match="not JSON"):
        await FairProvider(fair).generate_json("p", schema=SCHEMA)


async def test_accepted_without_output_is_classified_not_parsed():
    fair = FakeFair(Solve(output=None, reason_code="WEIRD"))
    with pytest.raises(ProviderError):
        await FairProvider(fair).generate_json("p", schema=SCHEMA)


# ── rejections: FAIR's own verdicts mapped onto the pool vocabulary ───


async def test_all_quota_exhausted_is_daily_exhaustion():
    fair = FakeFair(
        Solve(
            status="ESCALATION_REQUIRED",
            reason_code="ALL_FREE_MODELS_UNAVAILABLE",
            output=None,
            attempts=[
                Attempt(
                    "google_gemini_api", "gemini-3.6-flash", "QUOTA_FAILURE", "QUOTA_EXHAUSTED"
                ),
                Attempt("groq", "openai/gpt-oss-20b", "QUOTA_FAILURE", "QUOTA_EXHAUSTED"),
            ],
        )
    )
    with pytest.raises(ProviderExhaustedError) as info:
        await FairProvider(fair).generate_json("p", schema=SCHEMA)
    assert info.value.daily is True
    assert info.value.retry_after is None
    assert info.value.provider == "fair"
    assert "QUOTA_EXHAUSTED" in str(info.value)


async def test_rate_limited_members_are_short_exhaustion():
    fair = FakeFair(
        Solve(
            status="ESCALATION_REQUIRED",
            reason_code="ALL_FREE_MODELS_UNAVAILABLE",
            output=None,
            attempts=[
                Attempt("groq", "openai/gpt-oss-20b", "QUOTA_FAILURE", "RATE_LIMITED"),
                Attempt("groq", "openai/gpt-oss-120b", "QUOTA_FAILURE", "QUOTA_EXHAUSTED"),
            ],
        )
    )
    with pytest.raises(ProviderExhaustedError) as info:
        await FairProvider(fair).generate_json("p", schema=SCHEMA)
    assert info.value.daily is False
    assert info.value.retry_after == 60.0


async def test_unreachable_members_are_unavailable_not_exhausted():
    fair = FakeFair(
        Solve(
            status="ESCALATION_REQUIRED",
            reason_code="ALL_FREE_MODELS_UNAVAILABLE",
            output=None,
            attempts=[
                Attempt("groq", "openai/gpt-oss-20b", "QUOTA_FAILURE", "RATE_LIMITED"),
                Attempt("mistral", "mistral-small", "INFRA_FAILURE", "PROVIDER_UNAVAILABLE"),
            ],
        )
    )
    with pytest.raises(ProviderUnavailableError):
        await FairProvider(fair).generate_json("p", schema=SCHEMA)


async def test_no_attempts_at_all_is_unavailable():
    fair = FakeFair(
        Solve(status="ESCALATION_REQUIRED", reason_code="ALL_FREE_MODELS_UNAVAILABLE", output=None)
    )
    with pytest.raises(ProviderUnavailableError, match="no attempts"):
        await FairProvider(fair).generate_json("p", schema=SCHEMA)


async def test_quality_failure_is_a_plain_provider_error():
    fair = FakeFair(
        Solve(
            status="ESCALATION_REQUIRED",
            reason_code="ALL_FREE_MODELS_FAILED_QUALITY",
            output=None,
            best_quality_score=0.0,
            attempts=[Attempt("groq", "openai/gpt-oss-20b", "QUALITY_FAILURE")],
        )
    )
    with pytest.raises(ProviderError) as info:
        await FairProvider(fair).generate_json("p", schema=SCHEMA)
    assert type(info.value) is ProviderError  # not exhausted, not unavailable
    assert "best=0.0" in str(info.value)
    assert "required=82.0" in str(info.value)


async def test_fair_infrastructure_failure_is_unavailable():
    fair = FakeFair(Solve(status="FAILED", reason_code="VALIDATION_SERVICE_FAILED", output=None))
    with pytest.raises(ProviderUnavailableError, match="VALIDATION_SERVICE_FAILED"):
        await FairProvider(fair).generate_json("p", schema=SCHEMA)


async def test_solve_raising_is_wrapped_as_provider_error():
    fair = FakeFair(ValueError("Invalid expected JSON schema"))
    with pytest.raises(ProviderError, match="ValueError: Invalid expected JSON schema"):
        await FairProvider(fair).generate_json("p", schema={"type": "nonsense"})


async def test_classify_tolerates_bare_objects():
    """A SolveResponse-like object with only the essentials still classifies."""
    fair = FakeFair(
        SimpleNamespace(status="ESCALATION_REQUIRED", reason_code="SOMETHING_NEW", output=None)
    )
    with pytest.raises(ProviderError, match="SOMETHING_NEW"):
        await FairProvider(fair).generate_json("p", schema=SCHEMA)


# ── ping() — end-to-end liveness probe ────────────────────────────────


async def test_ping_ok_when_solve_is_accepted():
    fair = FakeFair(_accepted({"pong": True}))
    result = await FairProvider(fair).ping()
    assert isinstance(result, PingResult)
    assert result.ok is True
    assert result.provider_count == 2
    assert result.provider_ids == ["google_gemini_api", "groq"]
    assert result.solve_status == "ACCEPTED"
    assert result.solve_provider == "groq"
    assert result.solve_model == "openai/gpt-oss-20b"
    assert result.detail == "solve accepted"
    # Sends a real schema-checked task so "ok" cannot just mean "keys configured".
    call = fair.calls[0]
    assert call["expected_schema"]["required"] == ["pong"]


async def test_ping_reports_no_providers_without_calling_solve():
    class Empty(FakeFair):
        def providers(self):
            return []

    fair = Empty()
    result = await FairProvider(fair).ping()
    assert result.ok is False
    assert result.provider_count == 0
    assert result.provider_ids == []
    assert "no providers registered" in result.detail
    assert fair.calls == []  # no wasted solve when nothing is registered


async def test_ping_reports_providers_raising():
    class Broken(FakeFair):
        def providers(self):
            raise RuntimeError("router in bad state")

    result = await FairProvider(Broken()).ping()
    assert result.ok is False
    assert result.provider_count == 0
    assert "RuntimeError" in result.detail
    assert "router in bad state" in result.detail


async def test_ping_reports_solve_raising_with_provider_context():
    fair = FakeFair(ConnectionError("connection reset"))
    result = await FairProvider(fair).ping()
    assert result.ok is False
    assert result.provider_count == 2
    assert result.provider_ids == ["google_gemini_api", "groq"]
    assert "ConnectionError" in result.detail
    assert "connection reset" in result.detail


async def test_ping_reports_non_accepted_status_with_reason():
    fair = FakeFair(
        SimpleNamespace(
            status="ESCALATION_REQUIRED",
            reason_code="ALL_FREE_MODELS_UNAVAILABLE",
            output=None,
            provider_id=None,
            model_id=None,
        )
    )
    result = await FairProvider(fair).ping()
    assert result.ok is False
    assert result.solve_status == "ESCALATION_REQUIRED"
    assert "ALL_FREE_MODELS_UNAVAILABLE" in result.detail
