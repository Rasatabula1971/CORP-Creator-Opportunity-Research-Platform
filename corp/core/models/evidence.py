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
    NOT NULL since migration 5f5732311984 (R3); every write path must set it."""

    OBSERVATION = "observation"
    INFERENCE = "inference"


class EvidenceType(str, enum.Enum):
    """Which capability-provider interface (CORP1 Stage 4) produced this row.
    NOT NULL since migration 5f5732311984 (R3); every write path must set it."""

    PROBLEM = "problem"
    SEARCH_INTENT = "search_intent"
    TREND = "trend"
    PLANNING_INTENT = "planning_intent"
    TRANSACTION = "transaction"
    SOLUTION = "solution"
    MONETISATION = "monetisation"
    DISSATISFACTION = "dissatisfaction"


# Keys are the exact ``NormalizedContent.source_platform`` strings the adapters
# emit (see corp.workers.adapters.registry.KNOWN_PLATFORMS), not display names.
# Where the spec's adapter table lists several capabilities for one platform,
# the first-listed (primary) one is used for legacy collect() paths; the T3
# capability fan-out sets the precise type per interface call.
_PLATFORM_EVIDENCE_TYPE: dict[str, EvidenceType] = {
    "youtube": EvidenceType.PROBLEM,
    "tiktok": EvidenceType.PROBLEM,
    "reddit": EvidenceType.PROBLEM,
    "stackexchange": EvidenceType.PROBLEM,
    "hackernews": EvidenceType.PROBLEM,
    "quora": EvidenceType.PROBLEM,
    "googletrends": EvidenceType.TREND,
    "wikipedia": EvidenceType.TREND,
    "searchdemand": EvidenceType.SEARCH_INTENT,
    "pinterest": EvidenceType.PLANNING_INTENT,
    "marketplace": EvidenceType.TRANSACTION,
    "crowdfunding": EvidenceType.TRANSACTION,
    "kickstarter": EvidenceType.TRANSACTION,
    "indiegogo": EvidenceType.TRANSACTION,
    "google_shopping": EvidenceType.SOLUTION,
    "appstore": EvidenceType.SOLUTION,
    "product_hunt": EvidenceType.SOLUTION,
    "google_books": EvidenceType.SOLUTION,
    # Creator website / store detection: evidence the creator already sells.
    "web": EvidenceType.MONETISATION,
    "patreon_substack": EvidenceType.MONETISATION,
    "amazon_reviews": EvidenceType.DISSATISFACTION,
    "trustpilot": EvidenceType.DISSATISFACTION,
}


def infer_evidence_type(source_platform: str) -> EvidenceType | None:
    """Lenient platform → evidence-type lookup; write paths use the strict
    require_evidence_type() below."""
    return _PLATFORM_EVIDENCE_TYPE.get(source_platform.lower())


def require_evidence_type(source_platform: str) -> EvidenceType:
    """Strict form for write paths: an unmapped platform is a configuration
    error and must fail at the source, not as a NOT NULL violation at flush."""
    ev_type = infer_evidence_type(source_platform)
    if ev_type is None:
        raise ValueError(
            f"No evidence type mapped for platform {source_platform!r}; "
            "add it to corp.core.models.evidence._PLATFORM_EVIDENCE_TYPE"
        )
    return ev_type


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
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType), nullable=False)
    origin: Mapped[EvidenceOrigin] = mapped_column(Enum(EvidenceOrigin), nullable=False)
