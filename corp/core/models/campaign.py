import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from corp.core.models.base import Base, TimestampMixin, generate_uuid


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
        Enum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False
    )
    research_profile_version: Mapped[str | None] = mapped_column(String(50))

    target_niche_count: Mapped[int] = mapped_column(default=10, nullable=False)
    initial_creators_per_niche: Mapped[int] = mapped_column(default=10, nullable=False)
    creator_min_followers: Mapped[int] = mapped_column(default=10_000, nullable=False)
    creator_max_followers: Mapped[int] = mapped_column(default=200_000, nullable=False)
    human_gate_capacity: Mapped[int] = mapped_column(default=50, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
