from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from corp.core.models.creator import Creator
    from corp.core.models.niche import Niche


class CreatorNiche(TimestampMixin, Base):
    """Many-to-many: a creator may be associated with several niches (§14).

    This is the durable replacement for depending on the single
    Creator.niche string. That field is left in place for backward
    compatibility and is not removed by this slice.
    """

    __tablename__ = "creator_niches"
    __table_args__ = (
        Index("ix_creator_niches_creator_id", "creator_id"),
        Index("ix_creator_niches_niche_id", "niche_id"),
        Index(
            "ix_creator_niches_unique_pair", "creator_id", "niche_id", unique=True
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    niche_id: Mapped[str] = mapped_column(ForeignKey("niches.id"), nullable=False)
    # Nullable: not every observation of a creator-in-a-niche traces back to a
    # ResearchRun (e.g. manual association).
    discovery_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id"))

    confidence: Mapped[float | None] = mapped_column(Float)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    creator: Mapped["Creator"] = relationship(back_populates="creator_niches")
    niche: Mapped["Niche"] = relationship(back_populates="creator_niches")
