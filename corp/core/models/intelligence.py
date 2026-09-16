from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

EMBEDDING_DIM = 384


class ProblemObservation(TimestampMixin, Base):
    __tablename__ = "problem_observations"
    __table_args__ = (
        Index("ix_observations_evidence_id", "evidence_id"),
        Index("ix_observations_category", "category"),
        Index("ix_observations_source_side", "source_side"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    is_inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extraction_prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    # "audience" (comments) or "creator" (own titles/descriptions/transcripts)
    source_side: Mapped[str] = mapped_column(
        String(20), default="audience", server_default="audience", nullable=False
    )
    sentiment: Mapped[str | None] = mapped_column(String(20))
    urgency: Mapped[str | None] = mapped_column(String(20))
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    cluster_memberships: Mapped[list["ProblemClusterMember"]] = relationship(
        back_populates="observation"
    )


class ProblemCluster(TimestampMixin, Base):
    __tablename__ = "problem_clusters"
    __table_args__ = (Index("ix_clusters_creator_id", "creator_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str | None] = mapped_column(ForeignKey("creators.id"), nullable=True)
    # Set when a newer clustering run replaces this cluster. Rows are never deleted.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    recency_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_strength: Mapped[float] = mapped_column(Float, default=0.0)
    creator_count: Mapped[int] = mapped_column(Integer, default=1)
    model_version: Mapped[str | None] = mapped_column(String(100))

    members: Mapped[list["ProblemClusterMember"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class ProblemClusterMember(Base):
    __tablename__ = "problem_cluster_members"
    __table_args__ = (
        Index("ix_pcm_cluster_id", "cluster_id"),
        Index("ix_pcm_observation_id", "observation_id"),
        Index("ix_pcm_unique", "cluster_id", "observation_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    cluster_id: Mapped[str] = mapped_column(
        ForeignKey("problem_clusters.id"), nullable=False
    )
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("problem_observations.id"), nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)

    cluster: Mapped["ProblemCluster"] = relationship(back_populates="members")
    observation: Mapped["ProblemObservation"] = relationship(
        back_populates="cluster_memberships"
    )
