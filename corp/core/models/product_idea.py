"""Evidence-grounded product ideas (CORP1 Stage 5, T5).

A product idea is generated from one creator's ProblemCluster — never
invented independent of it, mirroring the same "niches come from evidence,
not imagination" invariant Stage 3 sets for niche discovery (T3) and the
same grounding mechanism this codebase already established for niche
naming (``niche_naming.check_grounding``, reused here unchanged).

The frozen T5 acceptance criterion read "traces to an Evidence.origin =
inference row for provenance". ``Evidence.origin`` exists (added by the
T0-gap migration a7b8c9d0e1f2 and set to ``inference`` by the intent and
competitive pipelines, which persist an LLM claim as its own Evidence row),
but a product idea is not itself evidence — it is a proposal grounded in
observation rows. So no synthetic inference row is written here; instead
`generation_method`/`generation_prompt_version`/`generation_model_version`
record how the idea was produced, and `ProductIdeaEvidence` (mirroring
`NicheCandidateEvidence`) is the real, queryable evidence trail back to the
raw `origin = observation` rows that grounded it. This is a disclosed
deviation from the literal T5 wording, recorded in the R2 ADR.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
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
    from corp.core.models.creator import Creator
    from corp.core.models.evidence import Evidence
    from corp.core.models.intelligence import ProblemCluster


class ProductIdeaType(str, enum.Enum):
    """Matches the CORP1 spec's product-idea vocabulary (Stage 1, step 6)."""

    TEMPLATE = "template"
    CALCULATOR = "calculator"
    NOTION_SYSTEM = "notion_system"
    GUIDE = "guide"
    CHECKLIST = "checklist"
    COURSE = "course"
    APP = "app"
    TRACKER = "tracker"
    DATABASE = "database"
    MEMBERSHIP = "membership"
    AI_TOOL = "ai_tool"


class ProductIdeaComplexity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProductIdea(TimestampMixin, Base):
    """One LLM-generated, evidence-grounded product idea for one creator's
    problem cluster. Never deleted; a newer generation run for the same
    cluster supersedes the still-active ideas of the previous run
    (``superseded_at``) — the same latest-wins convention clusters,
    scores, and niche candidates already use."""

    __tablename__ = "product_ideas"
    __table_args__ = (
        CheckConstraint("evidence_count >= 1", name="ck_product_ideas_has_evidence"),
        Index("ix_product_ideas_creator_id", "creator_id"),
        Index("ix_product_ideas_cluster_id", "problem_cluster_id"),
        Index("ix_product_ideas_superseded_at", "superseded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    problem_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("problem_clusters.id"), nullable=False
    )
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id"))

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    idea_type: Mapped[ProductIdeaType] = mapped_column(Enum(ProductIdeaType), nullable=False)
    complexity: Mapped[ProductIdeaComplexity] = mapped_column(
        Enum(ProductIdeaComplexity), nullable=False
    )
    price_min: Mapped[float | None] = mapped_column(Float)
    price_max: Mapped[float | None] = mapped_column(Float)
    fit_rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # Grounding, mirroring NicheCandidate's naming_terms/naming_method/
    # naming_confidence exactly (see module docstring).
    evidence_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_method: Mapped[str] = mapped_column(String(50), nullable=False, default="llm")
    generation_prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    generation_model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)

    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    creator: Mapped["Creator"] = relationship()
    cluster: Mapped["ProblemCluster"] = relationship()
    evidence: Mapped[list["ProductIdeaEvidence"]] = relationship(
        back_populates="product_idea", cascade="all, delete-orphan"
    )


class ProductIdeaEvidence(Base):
    """One evidence row's membership in one product idea's provenance
    trail. Mirrors NicheCandidateEvidence's join-table pattern exactly —
    the evidence itself is append-only and shared; this row is the
    reference."""

    __tablename__ = "product_idea_evidence"
    __table_args__ = (
        Index("ix_product_idea_evidence_unique", "product_idea_id", "evidence_id", unique=True),
        Index("ix_product_idea_evidence_evidence_id", "evidence_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    product_idea_id: Mapped[str] = mapped_column(
        ForeignKey("product_ideas.id"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), nullable=False)

    product_idea: Mapped["ProductIdea"] = relationship(back_populates="evidence")
    evidence_row: Mapped["Evidence"] = relationship()
