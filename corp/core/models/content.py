import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
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

    interactions: Mapped[list["AudienceInteraction"]] = relationship(
        back_populates="content_item", cascade="all, delete-orphan"
    )


class AudienceInteraction(TimestampMixin, Base):
    __tablename__ = "audience_interactions"

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

    content_item: Mapped["ContentItem"] = relationship(back_populates="interactions")
