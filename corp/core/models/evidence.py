import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from corp.core.models.base import Base, generate_uuid


class AccessMethod(str, enum.Enum):
    OFFICIAL = "official"
    VENDOR_SCRAPE = "vendor_scrape"
    OPEN = "open"


class ComplianceStatus(str, enum.Enum):
    COMPLIANT = "compliant"
    TOS_RISK = "tos_risk"
    PII_PRESENT = "pii_present"
    VERIFY = "verify"


class EvidenceOrigin(str, enum.Enum):
    """Whether the row is raw data or an LLM-derived claim (Provenance Invariant).
    Nullable at the DB level for backward compatibility with pre-Stage-4 rows;
    every row created by T3 onward must set it."""

    OBSERVATION = "observation"
    INFERENCE = "inference"


class EvidenceType(str, enum.Enum):
    """Which capability-provider interface (CORP1 Stage 4) produced this row.
    Nullable at the DB level for backward compatibility with pre-Stage-4
    rows; every row created by T3 onward must set it."""

    PROBLEM = "problem"
    SEARCH_INTENT = "search_intent"
    TREND = "trend"
    PLANNING_INTENT = "planning_intent"
    TRANSACTION = "transaction"
    SOLUTION = "solution"
    MONETISATION = "monetisation"
    DISSATISFACTION = "dissatisfaction"


class Evidence(Base):
    """Append-only evidence store. No UPDATE or DELETE — ever."""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_source", "source_type", "source_id"),
        Index("ix_evidence_platform", "source_platform"),
        Index("ix_evidence_research_run", "research_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    author_handle: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(500))
    access_method: Mapped[AccessMethod] = mapped_column(Enum(AccessMethod), nullable=False)
    compliance_status: Mapped[ComplianceStatus] = mapped_column(
        Enum(ComplianceStatus), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id"))
    evidence_type: Mapped[EvidenceType | None] = mapped_column(Enum(EvidenceType))
    origin: Mapped[EvidenceOrigin | None] = mapped_column(Enum(EvidenceOrigin))
