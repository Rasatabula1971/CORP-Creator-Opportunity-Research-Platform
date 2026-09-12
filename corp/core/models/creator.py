import enum

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid


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


class CreatorPlatformAccount(TimestampMixin, Base):
    __tablename__ = "creator_platform_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))
    subscriber_count: Mapped[int | None] = mapped_column()
    verified: Mapped[bool] = mapped_column(default=False)

    creator: Mapped["Creator"] = relationship(back_populates="platform_accounts")
