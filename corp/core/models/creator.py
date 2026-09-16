import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from corp.core.models.creator_niche import CreatorNiche


class CreatorStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    COLLECTING = "collecting"
    COLLECTED = "collected"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    CLUSTERING = "clustering"
    CLUSTERED = "clustered"
    SCORING = "scoring"
    SCORED = "scored"
    RESEARCH_COMPLETE = "research_complete"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WATCHING = "watching"
    DOSSIER_GENERATED = "dossier_generated"
    OUTREACH_READY = "outreach_ready"
    IN_OUTREACH = "in_outreach"
    PARTNERSHIP = "partnership"


class Creator(TimestampMixin, Base):
    __tablename__ = "creators"
    __table_args__ = (
        Index("ix_creators_status", "status"),
        Index("ix_creators_niche", "niche"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    niche: Mapped[str | None] = mapped_column(String(255))
    discovery_source: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[CreatorStatus] = mapped_column(
        Enum(CreatorStatus), default=CreatorStatus.DISCOVERED, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    platform_accounts: Mapped[list["CreatorPlatformAccount"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )
    # No delete cascade: a creator's niche-association history outlives any
    # single row referencing it — same reasoning as Niche.campaign_niches.
    creator_niches: Mapped[list["CreatorNiche"]] = relationship(back_populates="creator")


class CreatorPlatformAccount(TimestampMixin, Base):
    __tablename__ = "creator_platform_accounts"
    __table_args__ = (
        Index("ix_cpa_creator_id", "creator_id"),
        Index("ix_cpa_platform_handle", "platform", "handle", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))
    subscriber_count: Mapped[int | None] = mapped_column()
    verified: Mapped[bool] = mapped_column(default=False)
    # Point-in-time channel enrichment. MetricsSnapshot (metrics.py) tracks these
    # over time for growth/velocity scoring; these columns hold the latest value
    # for cheap reads that don't need history.
    total_view_count: Mapped[int | None] = mapped_column(Integer)
    video_count: Mapped[int | None] = mapped_column(Integer)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    country: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)

    creator: Mapped["Creator"] = relationship(back_populates="platform_accounts")
