"""Evidence-backed niche candidates (Slice 8, §15 Stage A / §16).

A candidate is a *staged* niche: a cluster of discovery evidence that has been
named but not yet canonicalized (Slice 9) or qualified (Slice 12). Two rules
the schema itself enforces:

* a candidate cannot exist without evidence — ``evidence_count >= 1`` and the
  member rows in ``niche_candidate_evidence`` are written in the same unit of
  work by the only code path that creates candidates;
* the name is traceable — ``naming_method`` says whether an LLM or the keyword
  labeller produced it, and ``naming_terms`` holds the evidence terms the
  label was justified with.

Candidates are never deleted. A new generation run for the same campaign
supersedes the still-staged candidates of the previous run (``superseded_at``),
the same latest-wins convention clusters and scores use.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from corp.core.models.campaign import Campaign
    from corp.core.models.evidence import Evidence
    from corp.core.models.niche import Niche


class NicheCandidateStatus(str, enum.Enum):
    STAGED = "staged"  # produced by generation, awaiting canonicalization
    DRILLING = "drilling"  # mid-recursion (CORP1 Stage 4): not yet specific
    # enough for a concrete product; the drill engine (T3) is re-querying
    # evidence at depth + 1. Distinguishes an in-progress drill from a
    # finished STAGED candidate awaiting canonicalization.
    PROMOTED = "promoted"  # became (or was attached to) a canonical Niche — Slice 9
    MERGED = "merged"  # resolved as an alias of another candidate/niche — Slice 9
    REJECTED = "rejected"  # broad domain, policy, or human decision


class NicheCandidate(TimestampMixin, Base):
    __tablename__ = "niche_candidates"
    __table_args__ = (
        CheckConstraint("evidence_count >= 1", name="ck_niche_candidates_has_evidence"),
        Index("ix_niche_candidates_campaign_id", "campaign_id"),
        Index("ix_niche_candidates_run_id", "research_run_id"),
        Index("ix_niche_candidates_status", "status"),
        Index("ix_niche_candidates_superseded_at", "superseded_at"),
        Index("ix_niche_candidates_parent_candidate_id", "parent_candidate_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    # The generation run that produced this candidate (NICHE_DISCOVERY, pipeline
    # "niche_candidates"). Provenance: run → campaign, run config → parameters.
    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), nullable=False)
    # Recursive drill-down tree (CORP1 Stage 4) — the specific edge this
    # candidate was drilled from. Mirrors Niche.parent_niche_id/depth.
    parent_candidate_id: Mapped[str | None] = mapped_column(ForeignKey("niche_candidates.id"))
    depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # "llm" — a model named the cluster from its member texts and every term it
    # cited appears in them; "keywords" — the deterministic c-TF-IDF-style label.
    naming_method: Mapped[str] = mapped_column(String(50), nullable=False)
    naming_terms: Mapped[list[str] | None] = mapped_column(JSON)
    naming_confidence: Mapped[float | None] = mapped_column(Float)
    # ADR-007: a broad domain ("Cars") may seed discovery but is not a niche.
    # Recorded here; acted on by qualification (Slice 12).
    is_broad_domain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Evidence diversity (§18): count and independence are separate numbers.
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    author_count: Mapped[int] = mapped_column(Integer, nullable=False)
    earliest_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    representative_text: Mapped[str | None] = mapped_column(Text)

    embedding_model: Mapped[str | None] = mapped_column(String(100))
    naming_prompt_version: Mapped[str | None] = mapped_column(String(50))
    naming_model_version: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[NicheCandidateStatus] = mapped_column(
        Enum(NicheCandidateStatus), default=NicheCandidateStatus.STAGED, nullable=False
    )
    niche_id: Mapped[str | None] = mapped_column(ForeignKey("niches.id"))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    campaign: Mapped["Campaign"] = relationship()
    niche: Mapped["Niche | None"] = relationship()
    members: Mapped[list["NicheCandidateEvidence"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    parent_candidate: Mapped["NicheCandidate | None"] = relationship(
        remote_side="NicheCandidate.id", back_populates="child_candidates"
    )
    child_candidates: Mapped[list["NicheCandidate"]] = relationship(
        back_populates="parent_candidate"
    )


class NicheCandidateEvidence(Base):
    """One evidence row's membership in one candidate, with its similarity to
    the candidate's centroid. The evidence itself is append-only and shared;
    this row is the reference."""

    __tablename__ = "niche_candidate_evidence"
    __table_args__ = (
        Index("ix_niche_candidate_evidence_unique", "candidate_id", "evidence_id", unique=True),
        Index("ix_niche_candidate_evidence_evidence_id", "evidence_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("niche_candidates.id"), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), nullable=False)
    similarity: Mapped[float | None] = mapped_column(Float)

    candidate: Mapped["NicheCandidate"] = relationship(back_populates="members")
    evidence: Mapped["Evidence"] = relationship()
