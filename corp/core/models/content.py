import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corp.core.models.base import Base, TimestampMixin, generate_uuid


class ContentType(str, enum.Enum):
    VIDEO = "video"
    POST = "post"
    STORY = "story"
    REEL = "reel"
    SHORT = "short"
    ARTICLE = "article"
    THREAD = "thread"


class InteractionType(str, enum.Enum):
    COMMENT = "comment"
    REPLY = "reply"
    QUESTION = "question"
    REVIEW = "review"


class ContentItem(TimestampMixin, Base):
    __tablename__ = "content_items"
    __table_args__ = (
        Index("ix_content_items_creator_id", "creator_id"),
        Index("ix_content_items_platform_ext", "platform", "external_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[ContentType] = mapped_column(Enum(ContentType), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    view_count: Mapped[int | None] = mapped_column(Integer)
    like_count: Mapped[int | None] = mapped_column(Integer)
    comment_count: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(String(500))
    topics: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10))
    is_short: Mapped[bool | None] = mapped_column(Boolean)

    interactions: Mapped[list["AudienceInteraction"]] = relationship(
        back_populates="content_item", cascade="all, delete-orphan"
    )


class AudienceInteraction(TimestampMixin, Base):
    __tablename__ = "audience_interactions"
    __table_args__ = (
        Index("ix_interactions_content_item_id", "content_item_id"),
        Index("ix_interactions_external_id", "external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    content_item_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    author_handle: Mapped[str | None] = mapped_column(String(255))
    interaction_type: Mapped[InteractionType] = mapped_column(
        Enum(InteractionType), default=InteractionType.COMMENT, nullable=False
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    like_count: Mapped[int | None] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(String(255))
    author_channel_id: Mapped[str | None] = mapped_column(String(255))

    content_item: Mapped["ContentItem"] = relationship(back_populates="interactions")
