"""Dossier persistence (CORP1 Stage 4's one new model).

Before this, the dossier was computed on the fly by an endpoint that
assembles ``corp.core.schemas.dossier.DossierResponse`` from Creator,
CreatorScore, OpportunityScore, ProblemCluster, etc. at request time — see
that module. This model persists it as a stored artifact instead, because
Stage 4's four-state decision gate (T8) needs a stable id to decide on, and
the CORP2 handoff package (T9) needs an immutable snapshot to hand off —
neither is possible against a value that only exists for the duration of one
request.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    pass


class DossierStatus(str, enum.Enum):
    """Denormalized mirror of the latest HumanDecision for fast dashboard
    queries. HumanDecision (append-only) remains the source of truth; this
    field is a read cache, not a second ledger."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WATCHING = "watching"
    RESEARCH_MORE_IN_PROGRESS = "research_more_in_progress"


class Dossier(TimestampMixin, Base):
    """One decision-ready dossier for one creator x niche x opportunity."""

    __tablename__ = "dossiers"
    __table_args__ = (
        Index("ix_dossiers_creator_id", "creator_id"),
        Index("ix_dossiers_niche_id", "niche_id"),
        Index("ix_dossiers_status", "status"),
        Index("ix_dossiers_superseded_at", "superseded_at"),
        Index(
            "uq_dossiers_active_creator_niche",
            "creator_id",
            "niche_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    niche_id: Mapped[str] = mapped_column(ForeignKey("niches.id"), nullable=False)
    opportunity_score_id: Mapped[str] = mapped_column(
        ForeignKey("opportunity_scores.id"), nullable=False
    )
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id"))

    # Rendered dossier sections (problem evidence, demand evidence,
    # competitive summary, recommendation) — see the Example Dossier Summary
    # in the CORP1 product spec. Shape intentionally mirrors
    # corp.core.schemas.dossier.DossierResponse's fields.
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[DossierStatus] = mapped_column(
        Enum(DossierStatus), default=DossierStatus.PENDING_REVIEW, nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Set when a newer dossier (e.g. produced by a Research More decision)
    # replaces this one. Same latest-wins convention as CreatorScore /
    # OpportunityScore / NicheCandidate. Rows are never deleted.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evidence: Mapped[list["DossierEvidence"]] = relationship(
        back_populates="dossier", cascade="all, delete-orphan"
    )


class DossierEvidence(Base):
    """One evidence row's membership in one dossier's CORP2 handoff trail.
    Mirrors NicheCandidateEvidence's join-table pattern — the evidence
    itself is append-only and shared; this row is the reference."""

    __tablename__ = "dossier_evidence"
    __table_args__ = (
        Index("ix_dossier_evidence_unique", "dossier_id", "evidence_id", unique=True),
        Index("ix_dossier_evidence_evidence_id", "evidence_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id"), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), nullable=False)

    dossier: Mapped["Dossier"] = relationship(back_populates="evidence")
