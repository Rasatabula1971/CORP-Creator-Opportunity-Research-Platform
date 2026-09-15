import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from corp.core.models.research_query import ResearchQuery


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


class RunScope(str, enum.Enum):
    CREATOR = "creator"
    NICHE = "niche"
    CROSS = "cross"


class RunStatus(str, enum.Enum):
    """Stored as plain strings on ResearchRun.status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"  # finished, but the failure rate exceeded the threshold
    FAILED = "failed"


class RunType(str, enum.Enum):
    """What kind of research this run is (§11), distinct from RunScope, which
    describes the breadth of an existing creator-pipeline run (one creator vs
    cross-creator). Defaults to CREATOR_RESEARCH so every pre-Slice-5 run
    (and every existing call site, none of which are retrofitted by this
    slice — that is "creator collector redesign", explicitly out of scope)
    keeps its current meaning unchanged."""

    NICHE_DISCOVERY = "niche_discovery"
    NICHE_VERIFICATION = "niche_verification"
    NICHE_QUALIFICATION = "niche_qualification"
    CREATOR_DISCOVERY = "creator_discovery"
    CREATOR_RESEARCH = "creator_research"


class ResearchRun(TimestampMixin, Base):
    __tablename__ = "research_runs"
    __table_args__ = (
        Index("ix_runs_creator_id", "creator_id"),
        Index("ix_runs_campaign_id", "campaign_id"),
        Index("ix_runs_niche_id", "niche_id"),
        Index("ix_runs_run_type", "run_type"),
        # Only the unambiguous half of §11's validation rules is enforced at
        # the DB level: NICHE_VERIFICATION requires niche_id. CREATOR_RESEARCH
        # is deliberately NOT constrained to require creator_id here, because
        # cross-creator clustering (ClusterPipeline.run(creator_id=None)) is
        # existing, designed creator-pipeline behavior that must keep working
        # unmodified — see docs/DECISIONS/0005. New call sites that need the
        # full rule set should use corp.core.state.research_run.validate_run_type.
        CheckConstraint(
            "run_type != 'niche_verification' OR niche_id IS NOT NULL",
            name="ck_research_runs_niche_verification_requires_niche",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    niche_id: Mapped[str | None] = mapped_column(ForeignKey("niches.id"), nullable=True)
    creator_id: Mapped[str | None] = mapped_column(ForeignKey("creators.id"), nullable=True)
    run_type: Mapped[str] = mapped_column(
        String(30),
        default=RunType.CREATOR_RESEARCH.value,
        server_default="creator_research",
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(
        String(20), default=RunScope.CREATOR.value, server_default="creator", nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    stats: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    prompt_versions: Mapped[dict | None] = mapped_column(JSONB)
    model_versions: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)

    # No delete cascade: query history is research memory (§13) and must
    # outlive the run that produced it — same reasoning as Slices 3–4.
    research_queries: Mapped[list["ResearchQuery"]] = relationship(
        back_populates="research_run"
    )
