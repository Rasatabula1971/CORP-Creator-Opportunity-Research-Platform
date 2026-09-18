"""Interface-contract tests for CORP1's capability providers (Stage 4/5, T1).

No real adapters implement these yet (T2) — these tests only exercise the
interfaces themselves: abstractness, the evidence_type mapping, and that
multiple inheritance across two capabilities does not collide.
"""

from datetime import UTC, datetime

import pytest

from corp.core.models.evidence import AccessMethod, ComplianceStatus, EvidenceType
from corp.workers.adapters.base import NormalizedContent
from corp.workers.providers.capabilities import (
    CAPABILITY_INTERFACES,
    DissatisfactionProvider,
    EvidenceProvider,
    MonetisationProvider,
    PlanningIntentProvider,
    ProblemProvider,
    SearchIntentProvider,
    SolutionProvider,
    TransactionProvider,
    TrendProvider,
)


def _content(text: str) -> NormalizedContent:
    return NormalizedContent(
        source_platform="fixture",
        content_type="comment",
        external_id="fixture_1",
        text=text,
        timestamp=datetime.now(tz=UTC),
        access_method=AccessMethod.OPEN,
        compliance_status=ComplianceStatus.COMPLIANT,
    )


# ---------- Base is abstract, not directly usable ----------


def test_evidence_provider_is_a_marker_base_with_no_behavior_of_its_own():
    """EvidenceProvider itself declares no abstract method (each capability's
    method lives on its own named interface below), so ABC does not block
    instantiating it directly — it exists purely so isinstance(x,
    EvidenceProvider) can identify any capability-implementing adapter."""
    provider = EvidenceProvider()
    assert isinstance(provider, EvidenceProvider)


@pytest.mark.parametrize("interface_cls", CAPABILITY_INTERFACES)
def test_each_interface_cannot_be_instantiated_without_its_method(interface_cls):
    with pytest.raises(TypeError):
        interface_cls()


@pytest.mark.parametrize("interface_cls", CAPABILITY_INTERFACES)
def test_each_interface_is_an_evidence_provider(interface_cls):
    assert issubclass(interface_cls, EvidenceProvider)


# ---------- evidence_type mapping: complete, one-to-one ----------


def test_capability_interfaces_covers_all_eight():
    assert len(CAPABILITY_INTERFACES) == 8


def test_every_evidence_type_has_exactly_one_interface():
    mapped = [cls.evidence_type for cls in CAPABILITY_INTERFACES]
    assert set(mapped) == set(EvidenceType)
    assert len(mapped) == len(set(mapped)), "an EvidenceType value maps to more than one interface"


# ---------- A concrete adapter can implement a single capability ----------


class _FakeProblemAdapter(ProblemProvider):
    async def fetch_problems(self, query: str) -> list[NormalizedContent]:
        return [_content(f"problem re: {query}")]


@pytest.mark.asyncio
async def test_single_capability_adapter_fetches():
    adapter = _FakeProblemAdapter()
    results = await adapter.fetch_problems("home espresso")
    assert len(results) == 1
    assert "home espresso" in results[0].text
    assert ProblemProvider.evidence_type == EvidenceType.PROBLEM


# ---------- Multiple inheritance across capabilities does not collide ----------


class _FakeRedditLikeAdapter(ProblemProvider, DissatisfactionProvider):
    """One adapter, two capability lenses on the same underlying source —
    mirrors the CORP1 spec's Reddit -> ProblemProvider, DissatisfactionProvider
    mapping."""

    async def fetch_problems(self, query: str) -> list[NormalizedContent]:
        return [_content(f"I wish there was a way to {query}")]

    async def fetch_dissatisfaction(self, query: str) -> list[NormalizedContent]:
        return [_content(f"{query} tools out there are all terrible")]


@pytest.mark.asyncio
async def test_multi_capability_adapter_both_methods_work_independently():
    adapter = _FakeRedditLikeAdapter()

    problems = await adapter.fetch_problems("track suspension setup")
    dissatisfaction = await adapter.fetch_dissatisfaction("track suspension setup")

    assert "I wish" in problems[0].text
    assert "terrible" in dissatisfaction[0].text
    # The two capabilities this one adapter satisfies map to different
    # EvidenceType values — read off the INTERFACE class, never off the
    # adapter instance.
    assert ProblemProvider.evidence_type == EvidenceType.PROBLEM
    assert DissatisfactionProvider.evidence_type == EvidenceType.DISSATISFACTION
    assert isinstance(adapter, ProblemProvider)
    assert isinstance(adapter, DissatisfactionProvider)


def test_reading_evidence_type_off_the_instance_is_the_trap_not_the_fix():
    """Stage 8 finding: the previous test proved correct usage works, but
    never showed WHY reading evidence_type off an adapter INSTANCE is
    unsafe. This test proves the collision directly: a class that
    implements both ProblemProvider and DissatisfactionProvider has only
    one instance-level `evidence_type` — Python's MRO resolves it to
    whichever base is listed first, silently discarding the other. This is
    exactly the footgun the module docstring and ADR-0031 warn about; it is
    demonstrated here, not just asserted in prose, so a future change that
    accidentally relies on `adapter.evidence_type` breaks this test."""
    adapter = _FakeRedditLikeAdapter()

    # The trap: this looks reasonable and type-checks, but is WRONG whenever
    # the caller actually wanted DISSATISFACTION (e.g. after calling
    # fetch_dissatisfaction()). It silently resolves to PROBLEM's value
    # because ProblemProvider is listed first in _FakeRedditLikeAdapter's
    # bases — never DissatisfactionProvider's, no matter which method was
    # actually called.
    assert adapter.evidence_type == EvidenceType.PROBLEM
    assert adapter.evidence_type != EvidenceType.DISSATISFACTION

    # The fix: callers must always resolve evidence_type from the interface
    # class they queried through (T3's contract), never from the instance.
    assert ProblemProvider.evidence_type == EvidenceType.PROBLEM
    assert DissatisfactionProvider.evidence_type == EvidenceType.DISSATISFACTION


def test_multi_capability_adapter_missing_one_method_still_abstract():
    """Implementing only one of two inherited capabilities must still fail —
    proves the abstractness isn't silently satisfied by the other method."""

    class _Incomplete(ProblemProvider, DissatisfactionProvider):
        async def fetch_problems(self, query: str) -> list[NormalizedContent]:
            return []

    with pytest.raises(TypeError):
        _Incomplete()  # type: ignore[abstract]


# ---------- Every named interface is reachable and correctly typed ----------


@pytest.mark.parametrize(
    ("interface_cls", "method_name", "expected_type"),
    [
        (ProblemProvider, "fetch_problems", EvidenceType.PROBLEM),
        (SearchIntentProvider, "fetch_search_intent", EvidenceType.SEARCH_INTENT),
        (TrendProvider, "fetch_trend", EvidenceType.TREND),
        (PlanningIntentProvider, "fetch_planning_intent", EvidenceType.PLANNING_INTENT),
        (TransactionProvider, "fetch_transactions", EvidenceType.TRANSACTION),
        (SolutionProvider, "fetch_solutions", EvidenceType.SOLUTION),
        (MonetisationProvider, "fetch_monetisation", EvidenceType.MONETISATION),
        (DissatisfactionProvider, "fetch_dissatisfaction", EvidenceType.DISSATISFACTION),
    ],
)
def test_interface_declares_its_named_method_and_evidence_type(
    interface_cls, method_name, expected_type
):
    assert hasattr(interface_cls, method_name)
    assert interface_cls.evidence_type == expected_type


@pytest.mark.asyncio
async def test_transaction_provider_fetch_transactions():
    """TransactionProvider is exercised directly (its method name doesn't
    match the fetch_<x> pattern of the parametrized case above)."""

    class _FakeMarketplaceAdapter(TransactionProvider):
        async def fetch_transactions(self, query: str) -> list[NormalizedContent]:
            return [_content(f"{query} template sold 500 times")]

    adapter = _FakeMarketplaceAdapter()
    results = await adapter.fetch_transactions("invoicing")
    assert "500 times" in results[0].text
    assert TransactionProvider.evidence_type == EvidenceType.TRANSACTION
