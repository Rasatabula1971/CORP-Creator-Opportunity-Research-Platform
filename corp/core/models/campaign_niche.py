import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from corp.core.models.campaign import Campaign
    from corp.core.models.niche import Niche


class CampaignNicheStatus(str, enum.Enum):
    """How far this niche has gotten within this specific campaign. Distinct
    from Niche.lifecycle_status, which tracks the niche's canonical, cross-
    campaign state."""

    DISCOVERED = "discovered"
    VERIFIED = "verified"
    SELECTED = "selected"
    REJECTED = "rejected"


class CampaignNiche(TimestampMixin, Base):
    """How one niche performed within one campaign (§12). Never overwrites
    Niche's own canonical history — the same niche can be scored differently
    across different campaigns, and every row here is additive.
    """

    __tablename__ = "campaign_niches"
    __table_args__ = (
        Index("ix_campaign_niches_campaign_id", "campaign_id"),
        Index("ix_campaign_niches_niche_id", "niche_id"),
        Index(
            "ix_campaign_niches_unique_pair", "campaign_id", "niche_id", unique=True
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    niche_id: Mapped[str] = mapped_column(ForeignKey("niches.id"), nullable=False)

    discovery_rank: Mapped[int | None] = mapped_column(Integer)
    # Score calculation is out of scope for this slice (§17/Slice 12); these
    # columns are placeholders a later slice will populate.
    qualification_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    research_completeness: Mapped[float | None] = mapped_column(Float)

    creator_count_observed: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    target_band_creator_count: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[CampaignNicheStatus] = mapped_column(
        Enum(CampaignNicheStatus),
        default=CampaignNicheStatus.DISCOVERED,
        server_default=CampaignNicheStatus.DISCOVERED.name,
        nullable=False,
    )
    selected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(Text)

    campaign: Mapped["Campaign"] = relationship(back_populates="campaign_niches")
    niche: Mapped["Niche"] = relationship(back_populates="campaign_niches")
