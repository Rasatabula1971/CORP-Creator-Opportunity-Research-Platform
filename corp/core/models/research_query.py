import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from corp.core.models.workflow import ResearchRun


class ResearchQueryStatus(str, enum.Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ResearchQuery(TimestampMixin, Base):
    """One executed search, recorded under its ResearchRun (§12, ADR-006).

    This is the query half of research memory (§13): what was searched, on
    which source, when, and what it yielded. Rows are additive — the same
    query may be recorded again in a later run, and the history of yields is
    exactly what lets a later slice judge whether repeating it is useful.
    """

    __tablename__ = "research_queries"
    __table_args__ = (
        Index("ix_research_queries_run_id", "research_run_id"),
        Index("ix_research_queries_source_query", "source", "query"),
        Index("ix_research_queries_executed_at", "executed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    research_run_id: Mapped[str] = mapped_column(
        ForeignKey("research_runs.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    # Client-side default: this is the time the search actually ran. A bare
    # server_default=now() would stamp every query in one transaction with the
    # transaction start time, which is not what a ledger of executions means.
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    results_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_results: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_results: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Pointer into bulk storage (§24) for the raw payload; never the payload itself.
    archive_reference: Mapped[str | None] = mapped_column(Text)

    status: Mapped[ResearchQueryStatus] = mapped_column(
        Enum(ResearchQueryStatus), default=ResearchQueryStatus.SUCCEEDED, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)

    research_run: Mapped["ResearchRun"] = relationship(back_populates="research_queries")
