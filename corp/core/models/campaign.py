import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from corp.core.models.campaign_niche import CampaignNiche


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class Campaign(TimestampMixin, Base):
    """The top-level research execution unit above niche and creator research.

    A campaign spans many niches and many creator ResearchRuns; it does not
    replace or alter the existing creator-bound pipeline.
    """

    __tablename__ = "campaigns"
    __table_args__ = (Index("ix_campaigns_status", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus),
        default=CampaignStatus.DRAFT,
        server_default=CampaignStatus.DRAFT.name,
        nullable=False,
    )
    research_profile_version: Mapped[str | None] = mapped_column(String(50))

    # server_default mirrors the migrations (f7a8b9c0d1e2) so the model documents
    # what a raw SQL insert gets and autogenerate stops proposing DROP DEFAULT.
    target_niche_count: Mapped[int] = mapped_column(
        default=10, server_default="10", nullable=False
    )
    initial_creators_per_niche: Mapped[int] = mapped_column(
        default=10, server_default="10", nullable=False
    )
    creator_min_followers: Mapped[int] = mapped_column(
        default=10_000, server_default="10000", nullable=False
    )
    creator_max_followers: Mapped[int] = mapped_column(
        default=200_000, server_default="200000", nullable=False
    )
    human_gate_capacity: Mapped[int] = mapped_column(
        default=50, server_default="50", nullable=False
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign_niches: Mapped[list["CampaignNiche"]] = relationship(back_populates="campaign")
