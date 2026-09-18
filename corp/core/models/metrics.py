"""Time-series snapshots of platform metrics.

ContentItem and CreatorPlatformAccount hold the latest counts. Every
collection run also appends one MetricsSnapshot per account and per content
item so growth (engagement velocity, follower velocity) can be computed from
two or more points in time. Append-only.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from corp.core.models.base import Base, generate_uuid


class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"
    __table_args__ = (
        Index("ix_snapshots_account_time", "platform_account_id", "captured_at"),
        Index("ix_snapshots_content_time", "content_item_id", "captured_at"),
        Index("ix_snapshots_run", "research_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("research_runs.id"))
    platform_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("creator_platform_accounts.id")
    )
    content_item_id: Mapped[str | None] = mapped_column(ForeignKey("content_items.id"))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    follower_count: Mapped[int | None] = mapped_column(Integer)
    view_count: Mapped[int | None] = mapped_column(Integer)
    like_count: Mapped[int | None] = mapped_column(Integer)
    comment_count: Mapped[int | None] = mapped_column(Integer)
    share_count: Mapped[int | None] = mapped_column(Integer)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
