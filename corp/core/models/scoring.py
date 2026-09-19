import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from corp.core.models.base import Base, TimestampMixin, generate_uuid


class ConfidenceBand(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class CreatorScore(TimestampMixin, Base):
    __tablename__ = "creator_scores"
    __table_args__ = (
        Index("ix_creator_scores_creator_id", "creator_id"),
        Index("ix_creator_scores_active", "superseded_at"),
        Index(
            "uq_creator_scores_active_creator",
            "creator_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    component_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    aggregate_score: Mapped[float] = mapped_column(Float, nullable=False)
    computed_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_band: Mapped[ConfidenceBand] = mapped_column(
        Enum(ConfidenceBand), nullable=False
    )
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id"))
    # Set when a newer scoring run replaces this row. Active rows have NULL here.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Unweighted context explaining the score (engagement, source mix, growth). Not hashed.
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class OpportunityScore(TimestampMixin, Base):
    __tablename__ = "opportunity_scores"
    __table_args__ = (
        Index("ix_opp_scores_creator_id", "creator_id"),
        Index("ix_opp_scores_cluster_id", "problem_cluster_id"),
        Index("ix_opportunity_scores_active", "superseded_at"),
        Index(
            "uq_opp_scores_active_creator_cluster",
            "creator_id",
            "problem_cluster_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    problem_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("problem_clusters.id"), nullable=False
    )
    component_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    aggregate_score: Mapped[float] = mapped_column(Float, nullable=False)
    computed_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_band: Mapped[ConfidenceBand] = mapped_column(
        Enum(ConfidenceBand), nullable=False
    )
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id"))
    # Set when a newer scoring run replaces this row. Active rows have NULL here.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Unweighted context explaining the score (engagement, source mix, growth). Not hashed.
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
