import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from corp.core.models.campaign_niche import CampaignNiche
    from corp.core.models.creator_niche import CreatorNiche


class NichePolicyClass(str, enum.Enum):
    """Configuration-driven policy tier (ADR-008); classification rules live
    outside this enum — this field only records the result."""

    STANDARD = "standard"
    RESTRICTED = "restricted"
    EXCLUDED = "excluded"


class NicheLifecycleStatus(str, enum.Enum):
    """The cycle from §7: CANDIDATE precedes verification; ACTIVE/EXPAND then
    cycle through COOLDOWN and RECHECK_DUE. Transitions are driven by later
    slices — this field only stores the current state."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    EXPAND = "expand"
    COOLDOWN = "cooldown"
    RECHECK_DUE = "recheck_due"


class Niche(TimestampMixin, Base):
    """Canonical niche identity. A broad domain (e.g. "Fitness") is a discovery
    input, not a qualified niche — see §5. Aliases map alternate wording onto
    one canonical row via NicheAlias.
    """

    __tablename__ = "niches"
    __table_args__ = (
        Index("ix_niches_canonical_name_ci", text("lower(canonical_name)"), unique=True),
        Index("ix_niches_lifecycle_status", "lifecycle_status"),
        Index("ix_niches_policy_class", "policy_class"),
        Index("ix_niches_parent_niche_id", "parent_niche_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_domain: Mapped[str | None] = mapped_column(String(255))
    # Recursive drill-down tree (CORP1 Stage 4). parent_domain above stays a
    # display label only; parent_niche_id is the source of truth for the
    # tree. depth 0 = a broad topic pulled straight from Trends; the drill
    # engine (T3) hard-caps recursion at depth 3.
    parent_niche_id: Mapped[str | None] = mapped_column(ForeignKey("niches.id"))
    depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    policy_class: Mapped[NichePolicyClass] = mapped_column(
        Enum(NichePolicyClass), default=NichePolicyClass.STANDARD, nullable=False
    )
    lifecycle_status: Mapped[NicheLifecycleStatus] = mapped_column(
        Enum(NicheLifecycleStatus), default=NicheLifecycleStatus.CANDIDATE, nullable=False
    )
    first_discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Doubles as the CORP1 Stage 3 research registry: a niche is eligible for
    # re-scan once next_recheck_at has passed (frozen at 90 days from
    # last_researched_at). No separate registry table — this is it.
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_recheck_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    aliases: Mapped[list["NicheAlias"]] = relationship(
        back_populates="niche", cascade="all, delete-orphan"
    )
    # No delete cascade: a niche's cross-campaign history must survive even if
    # a campaign referencing it were ever removed (Core Research Invariant #5).
    campaign_niches: Mapped[list["CampaignNiche"]] = relationship(back_populates="niche")
    creator_niches: Mapped[list["CreatorNiche"]] = relationship(back_populates="niche")
    parent_niche: Mapped["Niche | None"] = relationship(
        remote_side="Niche.id", back_populates="child_niches"
    )
    child_niches: Mapped[list["Niche"]] = relationship(back_populates="parent_niche")


class NicheAlias(TimestampMixin, Base):
    """Alternate wording that resolves to one canonical Niche. Existence of
    this table is what lets "home barista" and "home espresso" collapse to
    one niche instead of appearing as fake diversity — see §12.
    """

    __tablename__ = "niche_aliases"
    __table_args__ = (
        Index("ix_niche_aliases_niche_id", "niche_id"),
        Index("ix_niche_aliases_alias_ci", text("lower(alias)"), unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    niche_id: Mapped[str] = mapped_column(ForeignKey("niches.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)

    niche: Mapped["Niche"] = relationship(back_populates="aliases")
