import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from corp.core.models.base import Base, TimestampMixin, generate_uuid


class DecisionType(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    WATCH = "watch"


class Gate(str, enum.Enum):
    GATE_A = "gate_a"
    GATE_B = "gate_b"
    GATE_C = "gate_c"
    GATE_D = "gate_d"
    GATE_E = "gate_e"


class HumanDecision(Base):
    """Append-only. Every decision is a new row — never update or delete."""

    __tablename__ = "human_decisions"
    __table_args__ = (
        Index("ix_decisions_creator_id", "creator_id"),
        Index("ix_decisions_gate", "gate"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    opportunity_score_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunity_scores.id")
    )
    decision: Mapped[DecisionType] = mapped_column(Enum(DecisionType), nullable=False)
    gate: Mapped[Gate] = mapped_column(Enum(Gate), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_by: Mapped[str | None] = mapped_column(String(255))


class ResearchRun(TimestampMixin, Base):
    __tablename__ = "research_runs"
    __table_args__ = (Index("ix_runs_creator_id", "creator_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    prompt_versions: Mapped[dict | None] = mapped_column(JSONB)
    model_versions: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
