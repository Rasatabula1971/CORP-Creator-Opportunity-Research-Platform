import enum

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from corp.core.models.base import Base, TimestampMixin, generate_uuid


class CompetitorType(str, enum.Enum):
    DIRECT = "direct"
    SUBSTITUTE = "substitute"
    DIY_WORKAROUND = "diy_workaround"


class CompetitorStrength(str, enum.Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class Competitor(TimestampMixin, Base):
    """An existing product/creator/workaround already serving a problem cluster's audience."""

    __tablename__ = "competitors"
    __table_args__ = (Index("ix_competitors_cluster_id", "problem_cluster_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    problem_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("problem_clusters.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    competitor_type: Mapped[CompetitorType] = mapped_column(
        Enum(CompetitorType), nullable=False
    )
    strength: Mapped[CompetitorStrength] = mapped_column(
        Enum(CompetitorStrength), nullable=False
    )
    url: Mapped[str | None] = mapped_column(String(500))
    gap_notes: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"))
