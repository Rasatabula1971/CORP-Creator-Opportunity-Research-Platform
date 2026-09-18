"""CORP1 -> CORP2 Handoff Package (CORP1 Stage 5, T9).

Per the Stage 3 spec's own "CORP1 -> CORP2 Handoff Package (Frozen)"
section: "On Approve, CORP1 produces a decision package containing: the
full dossier; the complete evidence trail -- every evidence record and
source link the dossier was built from; the full niche drill-down path
... showing how specific the opportunity is; your review notes from the
decision gate. This mirrors the Acquisition system's dossier-snapshot
pattern: CORP2 references this package rather than querying the CORP1
research database directly."

This module only READS CORP1 tables and returns a plain, JSON-safe
snapshot -- it never writes to a CORP2 (``Acq*``-prefixed) table.
Producing that snapshot is CORP1's whole job here; how CORP2 actually
pulls or receives it (a file drop, a pull endpoint, a queue) is a later
task's concern, not this one's.

Reconstructing the package needs exactly five tables, all reachable from
``dossier_id`` alone: ``Dossier`` (the row itself), ``DossierEvidence``
joined to ``Evidence`` (the evidence trail T6 already links per dossier
-- "dossier_evidence" as the frozen task card names it), ``Niche``
walked via ``parent_niche_id`` (the drill-down path), and one direct
``HumanDecision`` lookup by ``dossier_id`` for the reviewer's own
decision-gate notes (the fourth bullet the acceptance criteria requires
-- nothing else. Dossier.content, built by T6's DossierGenerator before
any human ever reviewed it, cannot contain that text). No re-derivation
through ProblemCluster, OpportunityScore, CreatorScore or NicheCandidate
is needed or performed -- Dossier.content already carries the rendered
summary those were built from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.dossier import Dossier, DossierEvidence, DossierStatus
from corp.core.models.evidence import Evidence
from corp.core.models.niche import Niche
from corp.core.models.workflow import DecisionType, HumanDecision


@dataclass(frozen=True, slots=True)
class NichePathEntry:
    id: str
    canonical_name: str
    depth: int


@dataclass(frozen=True, slots=True)
class EvidenceTrailEntry:
    id: str
    source_type: str
    source_platform: str
    source_id: str
    source_url: str | None
    raw_text: str
    evidence_type: str | None
    access_method: str
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class HandoffPackage:
    """An immutable snapshot CORP2 references instead of querying CORP1's
    research database directly (Stage 3's own framing)."""

    dossier_id: str
    creator_id: str
    niche_id: str
    dossier_status: str
    dossier_content: dict[str, Any]
    generated_at: datetime
    niche_path: list[NichePathEntry] = field(default_factory=list)
    evidence_trail: list[EvidenceTrailEntry] = field(default_factory=list)
    decision_notes: str | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe rendering: datetimes as ISO 8601 strings, including
        ones nested inside niche_path/evidence_trail entries (asdict()
        already recurses into the nested dataclasses)."""
        return cast(dict[str, Any], _isoformat_nested(asdict(self)))


def _isoformat_nested(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_isoformat_nested(v) for v in value]
    if isinstance(value, dict):
        return {k: _isoformat_nested(v) for k, v in value.items()}
    return value


async def build_handoff_package(session: AsyncSession, dossier_id: str) -> HandoffPackage:
    """Build the frozen Stage 3 handoff package for one dossier.

    Raises ``ValueError`` if the dossier doesn't exist, or if its status
    is not ``APPROVED`` -- the package only makes sense once the human
    decision gate (T8) has actually approved it (Automation Matrix:
    "Handoff package creation" is "AUTO, triggered by Approve").
    """
    dossier = await session.get(Dossier, dossier_id)
    if dossier is None:
        raise ValueError(f"Dossier not found: {dossier_id}")
    if dossier.status != DossierStatus.APPROVED:
        raise ValueError(
            f"Dossier {dossier_id} is not approved (status={dossier.status.value}); "
            "the handoff package is only produced for an approved dossier"
        )

    evidence_rows = (
        await session.execute(
            select(Evidence)
            .join(DossierEvidence, DossierEvidence.evidence_id == Evidence.id)
            .where(DossierEvidence.dossier_id == dossier.id)
            .order_by(Evidence.collected_at)
        )
    ).scalars().all()

    niche_path = await _walk_niche_path(session, dossier.niche_id)

    decision = (
        await session.execute(
            select(HumanDecision)
            .where(
                HumanDecision.dossier_id == dossier.id,
                HumanDecision.decision == DecisionType.APPROVE,
            )
            .order_by(HumanDecision.decided_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return HandoffPackage(
        dossier_id=dossier.id,
        creator_id=dossier.creator_id,
        niche_id=dossier.niche_id,
        dossier_status=dossier.status.value,
        dossier_content=dossier.content,
        generated_at=dossier.generated_at,
        niche_path=niche_path,
        evidence_trail=[
            EvidenceTrailEntry(
                id=e.id,
                source_type=e.source_type,
                source_platform=e.source_platform,
                source_id=e.source_id,
                source_url=e.source_url,
                raw_text=e.raw_text,
                evidence_type=e.evidence_type.value if e.evidence_type else None,
                access_method=e.access_method.value,
                collected_at=e.collected_at,
            )
            for e in evidence_rows
        ],
        decision_notes=decision.rationale if decision else None,
        decided_at=decision.decided_at if decision else None,
        decided_by=decision.decided_by if decision else None,
    )


async def _walk_niche_path(session: AsyncSession, niche_id: str) -> list[NichePathEntry]:
    """Root -> leaf order (e.g. Automotive -> Track Builds -> Suspension),
    matching the Stage 3 spec's own example."""
    entries: list[NichePathEntry] = []
    current_id: str | None = niche_id
    seen: set[str] = set()
    while current_id is not None and current_id not in seen:
        seen.add(current_id)
        niche = await session.get(Niche, current_id)
        if niche is None:
            break
        entries.append(
            NichePathEntry(id=niche.id, canonical_name=niche.canonical_name, depth=niche.depth)
        )
        current_id = niche.parent_niche_id
    entries.reverse()
    return entries
