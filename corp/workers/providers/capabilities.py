"""Capability-provider interfaces (CORP1 Stage 4/5, T1).

Evidence sources are organized by WHAT they prove, not by platform — see the
CORP1 product spec's "Capability Interface Architecture" section. The
recursive niche-discovery engine (T3) fans a query out across every
capability, not across a hardcoded adapter list, so adding a new evidence
angle to the pipeline means adding a new adapter that implements the right
interface(s) (T2), never a new call site here.

Every method returns ``list[NormalizedContent]`` — the schema adapters
already emit (see :mod:`corp.workers.adapters.base`) — so wrapping an
existing adapter (T2) never means rewriting its collection logic, only
adding a thin method that delegates to it.

Each interface is a distinct ABC with its own uniquely named abstract
method. This is deliberate: an adapter can implement more than one
capability (e.g. Reddit posts are both problem evidence and dissatisfaction
evidence — see the CORP1 spec's adapter-to-capability table), and a shared
method name across interfaces would force one adapter class's `evidence_type`
to collide under Python's MRO the moment it implements two of them. With
distinct method names there is no collision: T3 already knows which
`EvidenceType` (corp.core.models.evidence, T0) applies from which method it
called, and each interface's own `evidence_type` ClassVar is read off the
**interface class**, e.g. ``ProblemProvider.evidence_type``, never off a
polymorphic instance (``adapter.evidence_type`` is not defined at all on
this base, precisely to keep that reference explicit).
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from corp.core.models.evidence import EvidenceType
from corp.workers.adapters.base import NormalizedContent


class EvidenceProvider(ABC):
    """Base for every capability interface below. Not implemented directly —
    always inherit one of the eight named interfaces instead."""

    # Declared, not assigned: every concrete interface below sets its own
    # value. This exists so static typing recognizes `some_interface_cls.
    # evidence_type` as valid on any EvidenceProvider subclass; it carries no
    # runtime value here and must never be read off this base directly.
    evidence_type: ClassVar[EvidenceType]


class ProblemProvider(EvidenceProvider):
    """Evidence that people have this problem — comments, questions, complaints."""

    evidence_type: ClassVar[EvidenceType] = EvidenceType.PROBLEM

    @abstractmethod
    async def fetch_problems(self, query: str) -> list[NormalizedContent]: ...


class SearchIntentProvider(EvidenceProvider):
    """Evidence that people actively look for answers (autocomplete, "people also ask")."""

    evidence_type: ClassVar[EvidenceType] = EvidenceType.SEARCH_INTENT

    @abstractmethod
    async def fetch_search_intent(self, query: str) -> list[NormalizedContent]: ...


class TrendProvider(EvidenceProvider):
    """Evidence of demand and its direction over time."""

    evidence_type: ClassVar[EvidenceType] = EvidenceType.TREND

    @abstractmethod
    async def fetch_trend(self, query: str) -> list[NormalizedContent]: ...


class PlanningIntentProvider(EvidenceProvider):
    """Evidence that people are researching and saving solutions, not yet bought."""

    evidence_type: ClassVar[EvidenceType] = EvidenceType.PLANNING_INTENT

    @abstractmethod
    async def fetch_planning_intent(self, query: str) -> list[NormalizedContent]: ...


class TransactionProvider(EvidenceProvider):
    """Evidence that solutions exist and people already pay for them."""

    evidence_type: ClassVar[EvidenceType] = EvidenceType.TRANSACTION

    @abstractmethod
    async def fetch_transactions(self, query: str) -> list[NormalizedContent]: ...


class SolutionProvider(EvidenceProvider):
    """Evidence of what solutions already exist — the competitive landscape."""

    evidence_type: ClassVar[EvidenceType] = EvidenceType.SOLUTION

    @abstractmethod
    async def fetch_solutions(self, query: str) -> list[NormalizedContent]: ...


class MonetisationProvider(EvidenceProvider):
    """Evidence that creators or products in this space already earn money."""

    evidence_type: ClassVar[EvidenceType] = EvidenceType.MONETISATION

    @abstractmethod
    async def fetch_monetisation(self, query: str) -> list[NormalizedContent]: ...


class DissatisfactionProvider(EvidenceProvider):
    """Evidence that current solutions are not good enough."""

    evidence_type: ClassVar[EvidenceType] = EvidenceType.DISSATISFACTION

    @abstractmethod
    async def fetch_dissatisfaction(self, query: str) -> list[NormalizedContent]: ...


# All eight, for T3's fan-out loop and for adapter-conformance tests (T2).
# Order matches the CORP1 spec's Evidence Sources section.
CAPABILITY_INTERFACES: tuple[type[EvidenceProvider], ...] = (
    ProblemProvider,
    SearchIntentProvider,
    TrendProvider,
    PlanningIntentProvider,
    TransactionProvider,
    SolutionProvider,
    MonetisationProvider,
    DissatisfactionProvider,
)
